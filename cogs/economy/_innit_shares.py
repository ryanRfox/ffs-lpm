from discord.ext import commands
import discord
from discord import app_commands
import datetime
import asyncio
import math
from tabulate import tabulate

def is_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

class Prediction:
    def __init__(self, question, end_time, options, creator_id, category=None):
        self.question = question
        self.end_time = end_time
        self.options = options
        self.creator_id = creator_id
        self.category = category
        self.bets = {option: {} for option in options}
        self.resolved = False
        self.result = None
        self.refunded = False
        self.total_bets = 0
        # Start with smaller initial liquidity to make price movements more noticeable
        self.liquidity_pool = {option: 100 for option in options}
        self.k_constant = 100 * 100  # Adjusted constant product

    def get_price(self, option, shares_to_buy):
        """Calculate price for buying shares using constant product formula"""
        if option not in self.liquidity_pool:
            return 0
        
        current_shares = self.liquidity_pool[option]
        other_shares = self.liquidity_pool[self.get_opposite_option(option)]
        
        # Using constant product formula: x * y = k
        new_shares = current_shares - shares_to_buy
        if new_shares <= 0:
            return float('inf')
        
        new_other_shares = self.k_constant / new_shares
        cost = new_other_shares - other_shares
        return max(0, cost)

    def get_opposite_option(self, option):
        """Get the opposite option in a binary market"""
        return [opt for opt in self.options if opt != option][0]

    def place_bet(self, user_id, option, points):
        """Place a bet using AMM pricing"""
        if option not in self.liquidity_pool:
            return False

        # Calculate shares user can buy with their points
        shares = self.calculate_shares_for_points(option, points)
        if shares <= 0:
            return False

        # Update liquidity pool
        self.liquidity_pool[option] -= shares
        opposite_option = self.get_opposite_option(option)
        self.liquidity_pool[opposite_option] += points

        # Record user's bet amount (not shares) for payout calculation
        if user_id in self.bets[option]:
            self.bets[option][user_id] += points
        else:
            self.bets[option][user_id] = points

        self.total_bets += points
        return True

    def calculate_shares_for_points(self, option, points):
        """Calculate how many shares user gets for their points"""
        current_shares = self.liquidity_pool[option]
        other_shares = self.liquidity_pool[self.get_opposite_option(option)]
        
        # Using constant product formula: x * y = k
        new_other_shares = other_shares + points
        new_shares = self.k_constant / new_other_shares
        shares_received = current_shares - new_shares
        return shares_received

    def get_odds(self):
        """Calculate current odds based on liquidity pool ratios"""
        total_shares = sum(self.liquidity_pool.values())
        return {
            option: total_shares / (amount * len(self.options)) 
            for option, amount in self.liquidity_pool.items()
        }

    def get_user_payout(self, user_id):
        """Calculate payout based on shares owned and final pool state"""
        if not self.resolved or self.result is None:
            return 0
        
        shares = self.bets[self.result].get(user_id, 0)
        if shares == 0:
            return 0
            
        # Calculate payout based on final pool state
        total_pool = sum(sum(user_bets.values()) for user_bets in self.bets.values())
        share_value = total_pool / sum(self.bets[self.result].values())
        return int(shares * share_value)

    def resolve(self, result):
        if result in self.options and not self.resolved:
            self.resolved = True
            self.result = result
            return True
        return False

    def get_total_bets(self):
        return self.total_bets

    def get_option_total_bets(self, option):
        return sum(self.bets[option].values()) if option in self.bets else 0

    def get_bet_history(self):
        history = []
        for option, bets in self.bets.items():
            for user_id, amount in bets.items():
                history.append((user_id, option, amount))
        return history

    def mark_as_refunded(self):
        self.refunded = True
        self.resolved = True

    def get_current_prices(self, points_to_spend=100):
        """Calculate current prices and potential shares for a given point amount"""
        prices = {}
        for option in self.options:
            shares = self.calculate_shares_for_points(option, points_to_spend)
            price_per_share = points_to_spend / shares if shares > 0 else float('inf')
            potential_payout = points_to_spend * (1 / price_per_share) if price_per_share > 0 else 0
            prices[option] = {
                'price_per_share': price_per_share,
                'potential_shares': shares,
                'potential_payout': potential_payout
            }
        return prices

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.points_manager = bot.points_manager
        self.predictions = []

    @app_commands.guild_only()
    @app_commands.command(name="create_prediction", description="Create a new prediction market")
    @app_commands.describe(
        question="The question for the prediction",
        duration="Duration format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)",
        options="Comma-separated list of prediction options",
        category="Category for the prediction (optional)"
    )
    async def create_prediction(
        self, 
        interaction: discord.Interaction, 
        question: str, 
        options: str, 
        duration: str,
        category: str = None
    ):
        # Immediately acknowledge the interaction
        await interaction.response.defer(ephemeral=False)
        
        try:
            # Process options
            options_list = [opt.strip() for opt in options.split(",")]
            
            # Validate options
            if len(options_list) < 2:
                await interaction.followup.send("You need at least two options for a prediction!", ephemeral=True)
                return
            
            # Process duration
            duration_parts = duration.split(",")
            if len(duration_parts) != 3:
                await interaction.followup.send("Duration must be in format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)", ephemeral=True)
                return
            
            days = int(duration_parts[0]) if duration_parts[0].strip() else 0
            hours = int(duration_parts[1]) if duration_parts[1].strip() else 0
            minutes = int(duration_parts[2]) if duration_parts[2].strip() else 0
            
            # Calculate total minutes
            total_minutes = (days * 24 * 60) + (hours * 60) + minutes
            if total_minutes <= 0:
                await interaction.followup.send("Duration must be greater than 0! Please specify days, hours, or minutes.", ephemeral=True)
                return
            
            # Create prediction object
            end_time = datetime.datetime.utcnow() + datetime.timedelta(minutes=total_minutes)
            new_prediction = Prediction(question, end_time, options_list, interaction.user.id, category)
            
            # Add to predictions list
            self.predictions.append(new_prediction)
            
            # Schedule prediction resolution
            asyncio.create_task(self.schedule_prediction_resolution(new_prediction))
            
            # Format duration string
            duration_parts = []
            if days > 0:
                duration_parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                duration_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                duration_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            duration_str = ", ".join(duration_parts)
            
            # Send confirmation message
            await interaction.followup.send(
                f"Prediction created:\n"
                f"Question: {question}\n"
                f"Options: {', '.join(options_list)}\n"
                f"Duration: {duration_str}\n"
                f"Category: {category if category else 'None'}",
                ephemeral=True
            )
            
        except ValueError:
            await interaction.followup.send("Invalid duration format! Please use numbers in format: days,hours,minutes (e.g., 1,2,30 or ,,30 or 1,,)", ephemeral=True)
        except Exception as e:
            try:
                await interaction.followup.send(f"Error creating prediction: {str(e)}", ephemeral=True)
            except:
                print(f"Failed to send error message: {str(e)}")

    async def schedule_prediction_resolution(self, prediction: Prediction):
        try:
            # Wait for betting period to end
            time_until_betting_ends = (prediction.end_time - datetime.datetime.utcnow()).total_seconds()
            if time_until_betting_ends > 0:
                print(f"DEBUG: Waiting {time_until_betting_ends} seconds for betting to end")
                await asyncio.sleep(time_until_betting_ends)
            
            # Don't proceed if already resolved
            if prediction.resolved:
                print("DEBUG: Prediction already resolved before betting end")
                return
                
            print(f"DEBUG: Betting period ended for {prediction.question}")
            
            # Notify creator that betting period has ended
            try:
                creator = await self.bot.fetch_user(prediction.creator_id)
                await creator.send(
                    f"🎲 Betting has ended for your prediction: '{prediction.question}'\n"
                    f"Please use `/resolve_prediction` to resolve the market.\n"
                    f"If not resolved within 48 hours, all bets will be automatically refunded."
                )
                print(f"DEBUG: Sent notification to creator {prediction.creator_id}")
            except Exception as e:
                print(f"DEBUG: Error notifying creator: {e}")

            # Wait 48 hours
            print("DEBUG: Starting 48-hour wait")
            await asyncio.sleep(48 * 3600)  # 48 hours in seconds
            
            # Check if resolved during wait
            if prediction.resolved:
                print("DEBUG: Prediction resolved during 48-hour wait")
                return
                
            print("DEBUG: Starting auto-refund process")
            
            # If we reach here, it's time to auto-refund
            prediction.mark_as_refunded()
            
            # Return all bets to users
            for option in prediction.bets:
                for user_id, amount in prediction.bets[option].items():
                    await self.points_manager.add_points(user_id, amount)
                    try:
                        user = await self.bot.fetch_user(user_id)
                        await user.send(
                            f"💰 Your bet of {amount:,} Points has been refunded for the expired market:\n"
                            f"'{prediction.question}'"
                        )
                    except Exception as e:
                        print(f"DEBUG: Error sending refund notification: {e}")
                    
        except Exception as e:
            print(f"DEBUG: Error in schedule_prediction_resolution: {e}")

    @app_commands.guild_only()
    @app_commands.command(name="bet", description="Place a bet on a prediction")
    async def bet(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # If there are no active predictions, inform the user
        active_predictions = [prediction for prediction in self.predictions if not prediction.resolved and prediction.end_time > datetime.datetime.utcnow()]
        if not active_predictions:
            await interaction.followup.send("No active predictions at the moment.", ephemeral=True)
            return

        # Get all unique categories
        categories = list(set(prediction.category for prediction in active_predictions if prediction.category))
        categories.append("All")

        # Create buttons for each category
        class CategoryButton(discord.ui.Button):
            def __init__(self, label, cog):
                super().__init__(label=label, style=discord.ButtonStyle.primary)
                self.cog = cog
                self.category = label

            async def callback(self, button_interaction: discord.Interaction):
                if self.category == "All":
                    filtered_predictions = active_predictions
                else:
                    filtered_predictions = [prediction for prediction in active_predictions if prediction.category == self.category]

                if not filtered_predictions:
                    await button_interaction.response.send_message("No predictions available for this category.", ephemeral=True)
                    return

                # Create a Select menu to allow the user to choose an active prediction
                class PredictionSelect(discord.ui.Select):
                    def __init__(self, predictions):
                        options = [
                            discord.SelectOption(label=prediction.question, description=f"Ends at {prediction.end_time.strftime('%Y-%m-%d %H:%M:%S UTC')} (Category: {prediction.category if prediction.category else 'None'})", value=str(index))
                            for index, prediction in enumerate(predictions)
                        ]
                        super().__init__(placeholder="Select a prediction to bet on...", min_values=1, max_values=1, options=options)

                    async def callback(self, interaction: discord.Interaction):
                        selected_index = int(self.values[0])
                        selected_prediction = filtered_predictions[selected_index]

                        # Check if the prediction is still active
                        if selected_prediction.end_time <= datetime.datetime.utcnow():
                            await interaction.response.send_message("This prediction has already ended!", ephemeral=True)
                            return

                        # Update the odds before showing the buttons
                        odds = selected_prediction.get_odds()

                        # Create buttons for the user to choose an option to bet on
                        class OptionButton(discord.ui.Button):
                            def __init__(self, label, prediction, cog):
                                # Get current prices for 100 point example
                                prices = prediction.get_current_prices(100)
                                price_info = prices[label]
                                
                                # Format the label to include price information
                                detailed_label = (
                                    f"{label}\n"
                                    f"Price: {price_info['price_per_share']:.2f} pts/share"
                                )
                                super().__init__(label=detailed_label, style=discord.ButtonStyle.primary)
                                self.prediction = prediction
                                self.cog = cog
                                self.option = label

                            async def callback(self, interaction: discord.Interaction):
                                class AmountInput(discord.ui.Modal, title="Place Your Bet"):
                                    def __init__(self, prediction, option, cog):
                                        super().__init__()
                                        self.prediction = prediction
                                        self.option = option
                                        self.cog = cog
                                        
                                        self.amount = discord.ui.TextInput(
                                            label=f"Enter amount to bet on {option}",
                                            style=discord.TextStyle.short,
                                            placeholder="Enter bet amount",
                                            required=True,
                                            min_length=1,
                                            max_length=10,
                                            default="100"
                                        )
                                        self.add_item(self.amount)

                                    async def on_submit(self, modal_interaction: discord.Interaction):
                                        try:
                                            amount = int(self.amount.value)
                                            if amount <= 0:
                                                await modal_interaction.response.send_message("Amount must be positive!", ephemeral=True)
                                                return

                                            # Check if prediction is still active
                                            if self.prediction.end_time <= datetime.datetime.utcnow():
                                                await modal_interaction.response.send_message("This prediction has already ended!", ephemeral=True)
                                                return

                                            # Check user's balance
                                            balance = await self.cog.points_manager.get_balance(modal_interaction.user.id)
                                            if balance < amount:
                                                await modal_interaction.response.send_message(f"You don't have enough Points! Your balance: {balance:,} Points", ephemeral=True)
                                                return

                                            # Calculate potential shares and payout
                                            pre_bet_prices = self.prediction.get_current_prices(amount)
                                            potential_shares = pre_bet_prices[self.option]['potential_shares']
                                            potential_payout = pre_bet_prices[self.option]['potential_payout']

                                            # Transfer points and place bet
                                            await self.cog.points_manager.transfer_points(modal_interaction.user.id, self.cog.bot.user.id, amount)
                                            self.prediction.place_bet(modal_interaction.user.id, self.option, amount)
                                            
                                            # Send confirmation
                                            await modal_interaction.response.send_message(
                                                f"✅ Bet placed: {amount:,} Points on '{self.option}'\n"
                                                f"📈 Shares received: {potential_shares:.2f}\n"
                                                f"💰 Potential payout if won: {potential_payout:.2f} points",
                                                ephemeral=True
                                            )

                                        except ValueError:
                                            await modal_interaction.response.send_message("Invalid amount entered!", ephemeral=True)

                                # Show the modal
                                await interaction.response.send_modal(AmountInput(self.prediction, self.option, self.cog))

                        class OptionButtonView(discord.ui.View):
                            def __init__(self, prediction, cog):
                                super().__init__()
                                odds = prediction.get_odds()
                                for option in prediction.options:
                                    button = OptionButton(label=f"{option}", prediction=prediction, cog=cog)
                                    self.add_item(button)

                        await interaction.response.send_message(content="Please select an option to bet on:", view=OptionButtonView(selected_prediction, self.cog), ephemeral=True)

                class PredictionSelectView(discord.ui.View):
                    def __init__(self, predictions, cog):
                        super().__init__()
                        select = PredictionSelect(predictions)
                        select.cog = cog
                        self.add_item(select)

                await button_interaction.response.send_message(content="Please select a prediction to bet on:", view=PredictionSelectView(filtered_predictions, self.cog), ephemeral=True)

        class CategoryButtonView(discord.ui.View):
            def __init__(self, categories, cog):
                super().__init__()
                for category in categories:
                    button = CategoryButton(label=category, cog=cog)
                    self.add_item(button)

        await interaction.followup.send("Please select a category:", view=CategoryButtonView(categories, self))

    @app_commands.guild_only()
    @app_commands.command(name="list_predictions", description="List all active predictions")
    async def list_predictions(self, interaction: discord.Interaction):
        try:
            if not self.predictions:
                await interaction.response.send_message("No active predictions at the moment.", ephemeral=True)
                return
            
            # Create main embed
            current_embed = discord.Embed(
                title="🎲 Prediction Markets",
                color=discord.Color.blue(),
                timestamp=datetime.datetime.utcnow()
            )

            # Group predictions by status
            active_markets = []
            inactive_markets = []
            resolved_markets = []
            refunded_markets = []  # New list for refunded markets

            for prediction in self.predictions:
                prices = prediction.get_current_prices(100)
                market_text = (
                    f"**Category:** {prediction.category or 'None'}\n"
                    f"**Pool:** {prediction.get_total_bets():,} Points\n"
                    f"**Current Prices:**\n"
                    + "\n".join([
                        f"• {opt}: {prices[opt]['price_per_share']:.2f} pts/share"
                        for opt in prediction.options
                    ]) + "\n"
                    f"**Ends:** <t:{int(prediction.end_time.timestamp())}:R>"
                )

                if prediction.resolved:
                    if prediction.refunded:
                        market_text = (
                            f"**Category:** {prediction.category or 'None'}\n"
                            f"**Pool:** {prediction.get_total_bets():,} Points\n"
                            f"**Ended:** <t:{int(prediction.end_time.timestamp())}:R>"
                        )
                        refunded_markets.append((prediction.question, market_text))  # Add to refunded markets
                    else:
                        market_text = (
                            f"**Category:** {prediction.category or 'None'}\n"
                            f"**Pool:** {prediction.get_total_bets():,} Points\n"
                            f"**Winner:** {prediction.result}\n"
                            f"**Ended:** <t:{int(prediction.end_time.timestamp())}:R>"
                        )
                        resolved_markets.append((prediction.question, market_text))
                elif prediction.end_time <= datetime.datetime.utcnow():
                    inactive_markets.append((prediction.question, market_text))
                else:
                    active_markets.append((prediction.question, market_text))

            def add_markets_to_embed(markets, title, embed):
                if not markets:
                    return embed
                
                MAX_FIELD_LENGTH = 1000  # Setting slightly below 1024 for safety
                current_content = ""
                field_count = 1
                
                for market_title, market_text in markets:
                    market_entry = f"**{market_title}**\n{market_text}\n\n"
                    
                    # If this single entry is too long, split it
                    if len(market_entry) > MAX_FIELD_LENGTH:
                        # If there's existing content, add it as a field first
                        if current_content:
                            field_title = f"{title} ({field_count})" if field_count > 1 else title
                            embed.add_field(name=field_title, value=current_content.strip(), inline=False)
                            field_count += 1
                            current_content = ""
                        
                        # Split the long entry into multiple fields
                        parts = []
                        remaining = market_entry
                        while remaining:
                            if len(remaining) <= MAX_FIELD_LENGTH:
                                parts.append(remaining)
                                break
                            
                            # Find the last newline before MAX_FIELD_LENGTH
                            split_point = remaining[:MAX_FIELD_LENGTH].rfind('\n')
                            if split_point == -1:
                                split_point = MAX_FIELD_LENGTH
                            
                            parts.append(remaining[:split_point])
                            remaining = remaining[split_point:].strip()
                        
                        # Add each part as a separate field
                        for part in parts:
                            field_title = f"{title} ({field_count})" if field_count > 1 else title
                            embed.add_field(name=field_title, value=part.strip(), inline=False)
                            field_count += 1
                        
                    # If adding this entry would exceed the limit, create a new field
                    elif len(current_content) + len(market_entry) > MAX_FIELD_LENGTH:
                        if current_content:
                            field_title = f"{title} ({field_count})" if field_count > 1 else title
                            embed.add_field(name=field_title, value=current_content.strip(), inline=False)
                            field_count += 1
                        current_content = market_entry
                    else:
                        current_content += market_entry
                
                # Add any remaining content
                if current_content:
                    field_title = f"{title} ({field_count})" if field_count > 1 else title
                    embed.add_field(name=field_title, value=current_content.strip(), inline=False)
                
                return embed

            # Add fields for each category
            if active_markets:
                current_embed = add_markets_to_embed(active_markets, "🟢 Active Markets", current_embed)
            if inactive_markets:
                current_embed = add_markets_to_embed(inactive_markets, "🟡 Pending Resolution", current_embed)
            if resolved_markets:
                current_embed = add_markets_to_embed(resolved_markets, "⭐ Resolved Markets", current_embed)
            if refunded_markets:  # Add refunded markets section
                current_embed = add_markets_to_embed(refunded_markets, "💰 Refunded Markets", current_embed)

            current_embed.set_footer(text="Use /bet to place bets on active markets")
            await interaction.response.send_message(embed=current_embed, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="resolve_prediction", description="Resolve a prediction")
    async def resolve_prediction_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Only show unresolved predictions created by this user
        unresolved_predictions = [
            pred for pred in self.predictions 
            if not pred.resolved and pred.creator_id == interaction.user.id
        ]
        
        if not unresolved_predictions:
            await interaction.followup.send(
                "You don't have any unresolved predictions to resolve. "
                "Only the creator of a prediction can resolve it.", 
                ephemeral=True
            )
            return

        class PredictionSelect(discord.ui.Select):
            def __init__(self, predictions, cog):
                self.cog = cog
                options = [
                    discord.SelectOption(
                        label=prediction.question, 
                        description=f"Ended at {prediction.end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", 
                        value=str(index)
                    )
                    for index, prediction in enumerate(predictions)
                ]
                super().__init__(placeholder="Select a prediction to resolve...", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction):
                selected_index = int(self.values[0])
                selected_prediction = unresolved_predictions[selected_index]

                class ResultSelect(discord.ui.Select):
                    def __init__(self, prediction, cog):
                        self.prediction = prediction
                        self.cog = cog
                        options = [
                            discord.SelectOption(label=option, value=option)
                            for option in prediction.options
                        ]
                        super().__init__(placeholder="Select the winning option...", min_values=1, max_values=1, options=options)

                    async def callback(self, interaction: discord.Interaction):
                        result = self.values[0]
                        if not self.prediction.resolve(result):
                            await interaction.response.send_message("This prediction has already been resolved!", ephemeral=True)
                            return

                        # Distribute payouts and notify winners
                        total_payout = self.prediction.get_total_bets()
                        winning_users = self.prediction.bets[result].items()
                        
                        # Process payouts and notifications for winners
                        for user_id, original_bet in winning_users:
                            payout = self.prediction.get_user_payout(user_id)
                            if payout > 0:
                                payout_amount = int(payout)
                                await self.cog.points_manager.add_points(user_id, payout_amount)
                                profit = payout_amount - original_bet
                                
                                try:
                                    user = await self.cog.bot.fetch_user(user_id)
                                    await user.send(
                                        f"🎉 You won {profit:,} Points on '{self.prediction.question}'!\n"
                                        f"Bet: {original_bet:,} → Payout: {payout_amount:,}"
                                    )
                                except Exception as e:
                                    print(f"Error sending winning notification to user {user_id}: {e}")

                        # Notify losing users
                        for option, bets in self.prediction.bets.items():
                            if option != result:  # This is a losing option
                                for user_id, bet_amount in bets.items():
                                    try:
                                        user = await self.cog.bot.fetch_user(user_id)
                                        await user.send(
                                            f"❌ You lost {bet_amount:,} Points on '{self.prediction.question}'.\n"
                                            f"The winning option was: {result}"
                                        )
                                    except Exception as e:
                                        print(f"Error sending losing notification to user {user_id}: {e}")

                        await interaction.response.send_message(
                            f"Prediction '{self.prediction.question}' resolved with result: '{result}'. "
                            f"Payouts have been distributed.", 
                            ephemeral=True
                        )

                view = discord.ui.View()
                view.add_item(ResultSelect(selected_prediction, self.cog))
                await interaction.response.send_message("Please select the winning option:", view=view, ephemeral=True)

        view = discord.ui.View()
        view.add_item(PredictionSelect(unresolved_predictions, self))
        await interaction.followup.send("Please select a prediction to resolve:", view=view, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))
