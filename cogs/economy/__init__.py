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
        self.bets = {option: {} for option in options}  # {option: {user_id: amount}}
        self.resolved = False
        self.result = None
        self.refunded = False
        self.total_bets = 0

    def place_bet(self, user_id, option, amount):
        if option in self.bets:
            if user_id in self.bets[option]:
                self.bets[option][user_id] += amount
            else:
                self.bets[option][user_id] = amount
            self.total_bets += amount

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

    def get_user_payout(self, user_id):
        if not self.resolved or self.result is None:
            return 0
        total_bets = self.get_total_bets()
        winning_pool = self.get_option_total_bets(self.result)
        user_bet = self.bets[self.result].get(user_id, 0)
        if user_bet == 0:
            return 0
        return total_bets * (user_bet / winning_pool)

    def get_odds(self):
        odds = {}
        total_bets = self.get_total_bets()
        for option in self.options:
            option_bets = self.get_option_total_bets(option)
            odds[option] = (total_bets / option_bets) if option_bets > 0 else float('inf')
        return odds

    def get_bet_history(self):
        history = []
        for option, bets in self.bets.items():
            for user_id, amount in bets.items():
                history.append((user_id, option, amount))
        return history

    def mark_as_refunded(self):
        self.refunded = True
        self.resolved = True

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.points_manager = bot.points_manager
        self.predictions = []

    @app_commands.guild_only()
    @app_commands.command(name="create_prediction", description="Create a new prediction market")
    @app_commands.describe(
        question="The question for the prediction",
        duration="Duration of the prediction in minutes",
        options="Comma-separated list of prediction options",
        category="Category for the prediction (optional)"
    )
    async def create_prediction(self, interaction: discord.Interaction, question: str, duration: int, options: str, category: str = None):
        # Immediately acknowledge the interaction
        await interaction.response.defer(ephemeral=False)
        
        try:
            # Process options
            options_list = [opt.strip() for opt in options.split(",")]
            
            # Validate
            if len(options_list) < 2:
                await interaction.followup.send("You need at least two options for a prediction!", ephemeral=True)
                return
            
            # Create prediction object
            end_time = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration)
            new_prediction = Prediction(question, end_time, options_list, interaction.user.id, category)
            
            # Add to predictions list
            self.predictions.append(new_prediction)
            
            # Schedule prediction resolution
            asyncio.create_task(self.schedule_prediction_resolution(new_prediction))
            
            # Send confirmation message
            await interaction.followup.send(
                f"Prediction created:\n"
                f"Question: {question}\n"
                f"Options: {', '.join(options_list)}\n"
                f"Duration: {duration} minutes\n"
                f"Category: {category if category else 'None'}",
                ephemeral=True
            )
            
        except Exception as e:
            # Error handling
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
                                super().__init__(label=label, style=discord.ButtonStyle.primary)
                                self.prediction = prediction
                                self.cog = cog
                                self.option = label.split(' ')[0]  # Extract the option name from the label

                            async def callback(self, button_interaction: discord.Interaction):
                                # Ask the user to enter the amount to bet
                                class AmountInput(discord.ui.Modal, title="Enter Bet Amount"):
                                    def __init__(self, prediction, option, cog):
                                        super().__init__()
                                        self.prediction = prediction
                                        self.option = option
                                        self.cog = cog
                                        self.amount = discord.ui.TextInput(label="Amount", style=discord.TextStyle.short, placeholder="Enter the amount of points to bet", required=True)
                                        self.add_item(self.amount)

                                    async def on_submit(self, amount_interaction: discord.Interaction):
                                        try:
                                            amount = int(self.amount.value)
                                            if amount <= 0:
                                                await amount_interaction.response.send_message("Amount must be positive!", ephemeral=True)
                                                return

                                            # Check if the prediction is still active
                                            if self.prediction.end_time <= datetime.datetime.utcnow():
                                                await amount_interaction.response.send_message("This prediction has already ended!", ephemeral=True)
                                                return

                                            balance = await self.cog.points_manager.get_balance(amount_interaction.user.id)
                                            if balance < amount:
                                                await amount_interaction.response.send_message(f"You don't have enough Points! Your balance: {balance:,} Points", ephemeral=True)
                                                return

                                            await self.cog.points_manager.transfer_points(amount_interaction.user.id, self.cog.bot.user.id, amount)
                                            self.prediction.place_bet(amount_interaction.user.id, self.option, amount)
                                            odds = self.prediction.get_odds()
                                            
                                            # Delete the original option selection message
                                            try:
                                                await amount_interaction.message.delete()
                                            except:
                                                pass  # Silently fail if we can't delete the message
                                            
                                            # Respond to the modal interaction
                                            await amount_interaction.response.send_message(
                                                f"Bet placed: {amount:,} Points on '{self.option}'!\nCurrent Odds for '{self.option}': {odds[self.option]:.2f}",
                                                ephemeral=True
                                            )

                                        except ValueError:
                                            await amount_interaction.response.send_message("Invalid amount entered! Please enter a valid number.", ephemeral=True)
                                        except Exception as e:
                                            if not amount_interaction.response.is_done():
                                                await amount_interaction.response.send_message(f"Error placing bet: {str(e)}", ephemeral=True)
                                            else:
                                                await amount_interaction.followup.send(f"Error placing bet: {str(e)}", ephemeral=True)

                                await button_interaction.response.send_modal(AmountInput(self.prediction, self.option, self.cog))

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
                odds_text = "\n".join([f"• {opt}: {odds:.2f}x" for opt, odds in prediction.get_odds().items()])
                total_pool = prediction.get_total_bets()
                
                market_text = (
                    f"**Category:** {prediction.category or 'None'}\n"
                    f"**Pool:** {total_pool:,} Points\n"
                    f"**Odds:** " + " | ".join([f"{opt}: {odds:.2f}x" for opt, odds in prediction.get_odds().items()]) + "\n"
                    f"**Ends:** <t:{int(prediction.end_time.timestamp())}:R>"
                )

                if prediction.resolved:
                    if prediction.refunded:
                        market_text = (
                            f"**Category:** {prediction.category or 'None'}\n"
                            f"**Pool:** {total_pool:,} Points\n"
                            f"**Ended:** <t:{int(prediction.end_time.timestamp())}:R>"
                        )
                        refunded_markets.append((prediction.question, market_text))  # Add to refunded markets
                    else:
                        market_text = (
                            f"**Category:** {prediction.category or 'None'}\n"
                            f"**Pool:** {total_pool:,} Points\n"
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
