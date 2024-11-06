from discord.ext import commands
import discord
from discord import app_commands
import datetime
import asyncio
import math

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
        self.total_bets = 0

    def place_bet(self, user_id, option, amount):
        if option in self.bets:
            if user_id in self.bets[option]:
                self.bets[option][user_id] += amount
            else:
                self.bets[option][user_id] = amount
            self.total_bets += amount

    def resolve(self, result):
        if result in self.options:
            self.resolved = True
            self.result = result

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
        await interaction.response.defer(ephemeral=True)
        
        options_list = [opt.strip() for opt in options.split(",")]
        if len(options_list) < 2:
            await interaction.followup.send("You need at least two options for a prediction!", ephemeral=True)
            return
        
        end_time = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration)
        new_prediction = Prediction(question, end_time, options_list, interaction.user.id, category)
        self.predictions.append(new_prediction)

        await interaction.followup.send(
            f"Prediction created: {question}\nOptions: {', '.join(options_list)}\nEnds in {duration} minutes.\nCategory: {category if category else 'None'}",
            ephemeral=True
        )

        # Schedule the resolution of the prediction
        asyncio.create_task(self.schedule_prediction_resolution(new_prediction))

    async def schedule_prediction_resolution(self, prediction: Prediction):
        await asyncio.sleep((prediction.end_time - datetime.datetime.utcnow()).total_seconds())
        if not prediction.resolved:
            await self.resolve_prediction(prediction)

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
                                            await amount_interaction.response.send_message(
                                                f"Bet placed: {amount:,} Points on '{self.option}'!\nCurrent Odds: {', '.join([f'{opt}: {odds[opt]:.2f}' for opt in self.prediction.options])}",
                                                ephemeral=True
                                            )

                                            # Update the odds for the current prediction
                                            await button_interaction.response.edit_message(
                                                content="Please select an option to bet on:",
                                                view=OptionButtonView(self.prediction, self.cog)
                                            )

                                        except ValueError:
                                            await amount_interaction.response.send_message("Invalid amount entered! Please enter a valid number.", ephemeral=True)
                                        except Exception as e:
                                            await amount_interaction.response.send_message(f"Error placing bet: {str(e)}", ephemeral=True)

                                await button_interaction.response.send_modal(AmountInput(self.prediction, self.option, self.cog))

                        class OptionButtonView(discord.ui.View):
                            def __init__(self, prediction, cog):
                                super().__init__()
                                odds = prediction.get_odds()
                                for option in prediction.options:
                                    button = OptionButton(label=f"{option} (Odds: {odds[option]:.2f})", prediction=prediction, cog=cog)
                                    self.add_item(button)

                        await interaction.response.edit_message(content = "Please select an option to bet on:", view=OptionButtonView(selected_prediction, self.cog))

                class PredictionSelectView(discord.ui.View):
                    def __init__(self, predictions, cog):
                        super().__init__()
                        select = PredictionSelect(predictions)
                        select.cog = cog
                        self.add_item(select)

                await button_interaction.response.edit_message(content = "Please select a prediction to bet on:", view=PredictionSelectView(filtered_predictions, self.cog))

        class CategoryButtonView(discord.ui.View):
            def __init__(self, categories, cog):
                super().__init__()
                for category in categories:
                    button = CategoryButton(label=category, cog=cog)
                    self.add_item(button)

        await interaction.edit_original_response(content = "Please select a category:", view=CategoryButtonView(categories, self))

    @app_commands.guild_only()
    @app_commands.command(name="list_predictions", description="List all active predictions")
    async def list_predictions(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.predictions:
            await interaction.followup.send("No active predictions at the moment.", ephemeral=True)
            return

        active_predictions = [
            f"{index}. {prediction.question} (Ends at {prediction.end_time.strftime('%Y-%m-%d %H:%M:%S UTC')})\nCategory: {prediction.category if prediction.category else 'None'}\nOdds: {', '.join([f'{opt}: {odds:.2f}' for opt, odds in prediction.get_odds().items()])}"
            for index, prediction in enumerate(self.predictions) if not prediction.resolved and prediction.end_time > datetime.datetime.utcnow()
        ]
        
        if not active_predictions:
            await interaction.followup.send("No active predictions at the moment.", ephemeral=True)
            return

        labeled_predictions = [f"{index}. {prediction}" for index, prediction in enumerate(active_predictions)]
        await interaction.followup.send("\n\n".join(labeled_predictions), ephemeral=True)

    async def resolve_prediction(self, prediction: Prediction):
        channel = self.bot.get_channel(YOUR_CHANNEL_ID)  # Replace with your channel ID
        if not channel:
            return

        if not prediction.resolved:
            await channel.send(f"The prediction '{prediction.question}' has ended! Admins, please resolve it using `/resolve_prediction`. Options were: {', '.join(prediction.options)}")

    @app_commands.guild_only()
    @app_commands.command(name="resolve_prediction", description="Resolve a prediction")
    async def resolve_prediction_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        unresolved_predictions = [prediction for prediction in self.predictions if not prediction.resolved]
        if not unresolved_predictions:
            await interaction.followup.send("No unresolved predictions at the moment.", ephemeral=True)
            return

        # Create a Select menu to allow the admin to choose an unresolved prediction
        class PredictionSelect(discord.ui.Select):
            def __init__(self, predictions):
                options = [
                    discord.SelectOption(label=prediction.question, description=f"Ended at {prediction.end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", value=str(index))
                    for index, prediction in enumerate(predictions)
                ]
                super().__init__(placeholder="Select a prediction to resolve...", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction):
                selected_index = int(self.values[0])
                selected_prediction = unresolved_predictions[selected_index]

                # Create a Select menu for choosing the winning option
                class ResultSelect(discord.ui.Select):
                    def __init__(self, prediction):
                        options = [
                            discord.SelectOption(label=option, value=option)
                            for option in prediction.options
                        ]
                        super().__init__(placeholder="Select the winning option...", min_values=1, max_values=1, options=options)

                    async def callback(self, interaction: discord.Interaction):
                        result = self.values[0]
                        selected_prediction.resolve(result)

                        # Distribute payouts
                        total_payout = selected_prediction.get_total_bets()
                        for user_id in selected_prediction.bets[result]:
                            payout = selected_prediction.get_user_payout(user_id)
                            if payout > 0:
                                await self.cog.points_manager.add_points(user_id, int(payout))

                        await interaction.response.send_message(f"Prediction '{selected_prediction.question}' resolved with result: '{result}'. Payouts have been distributed.", ephemeral=True)

                # Send a message to select the winning option
                class ResultSelectView(discord.ui.View):
                    def __init__(self, prediction, cog):
                        super().__init__()
                        select = ResultSelect(prediction)
                        select.cog = cog
                        self.add_item(select)

                await interaction.response.send_message("Please select the winning option:", view=ResultSelectView(selected_prediction, self.cog))

        class PredictionSelectView(discord.ui.View):
            def __init__(self, predictions, cog):
                super().__init__()
                select = PredictionSelect(predictions)
                select.cog = cog
                self.add_item(select)

        await interaction.followup.send("Please select a prediction to resolve:", view=PredictionSelectView(unresolved_predictions, self))

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))