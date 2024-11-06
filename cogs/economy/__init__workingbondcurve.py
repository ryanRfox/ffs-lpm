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
    def __init__(self, question, end_time, options, creator_id):
        self.question = question
        self.end_time = end_time
        self.options = options
        self.creator_id = creator_id
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
        options="Comma-separated list of prediction options"
    )
    
    async def create_prediction(self, interaction: discord.Interaction, question: str, duration: int, options: str):
        await interaction.response.defer(ephemeral=True)
        
        options_list = [opt.strip() for opt in options.split(",")]
        if len(options_list) < 2:
            await interaction.followup.send("You need at least two options for a prediction!", ephemeral=True)
            return
        
        end_time = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration)
        new_prediction = Prediction(question, end_time, options_list, interaction.user.id)
        self.predictions.append(new_prediction)

        await interaction.followup.send(
            f"Prediction created: {question}\nOptions: {', '.join(options_list)}\nEnds in {duration} minutes.",
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
    @app_commands.describe(
        prediction_index="The index of the prediction to bet on (check with /list_predictions)",
        option="The option to bet on",
        amount="Amount of Points to bet"
    )
    async def bet(self, interaction: discord.Interaction, prediction_index: int, option: str, amount: int):
        await interaction.response.defer(ephemeral=True)

        if prediction_index < 0 or prediction_index >= len(self.predictions):
            await interaction.followup.send("Invalid prediction index!", ephemeral=True)
            return
        
        prediction = self.predictions[prediction_index]
        if datetime.datetime.utcnow() >= prediction.end_time:
            await interaction.followup.send("This prediction has already ended!", ephemeral=True)
            return

        if option not in prediction.options:
            await interaction.followup.send(f"Invalid option! Available options: {', '.join(prediction.options)}", ephemeral=True)
            return

        if amount <= 0:
            await interaction.followup.send("Amount must be positive!", ephemeral=True)
            return

        try:
            balance = await self.points_manager.get_balance(interaction.user.id)
            if balance < amount:
                await interaction.followup.send(f"You don't have enough Points! Your balance: {balance:,} Points", ephemeral=True)
                return

            await self.points_manager.transfer_points(interaction.user.id, self.bot.user.id, amount)
            prediction.place_bet(interaction.user.id, option, amount)
            odds = prediction.get_odds()
            await interaction.followup.send(
                f"Bet placed: {amount:,} Points on '{option}'!\nCurrent Odds: {', '.join([f'{opt}: {odds[opt]:.2f}' for opt in prediction.options])}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"Error placing bet: {str(e)}", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="list_predictions", description="List all active predictions")
    async def list_predictions(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.predictions:
            await interaction.followup.send("No active predictions at the moment.", ephemeral=True)
            return

        active_predictions = [
            f"{index}. {prediction.question} (Ends at {prediction.end_time.strftime('%Y-%m-%d %H:%M:%S UTC')})\nOdds: {', '.join([f'{opt}: {odds:.2f}' for opt, odds in prediction.get_odds().items()])}"
            for index, prediction in enumerate(self.predictions) if not prediction.resolved
        ]
        
        if not active_predictions:
            await interaction.followup.send("No active predictions at the moment.", ephemeral=True)
            return

        await interaction.followup.send("\n\n".join(active_predictions), ephemeral=True)

    async def resolve_prediction(self, prediction: Prediction):
        channel = self.bot.get_channel(YOUR_CHANNEL_ID)  # Replace with your channel ID
        if not channel:
            return

        if not prediction.resolved:
            await channel.send(f"The prediction '{prediction.question}' has ended! Admins, please resolve it using `/resolve_prediction`. Options were: {', '.join(prediction.options)}")

    @app_commands.guild_only()
    @app_commands.command(name="resolve_prediction", description="Resolve a prediction")
    @app_commands.describe(
        prediction_index="The index of the prediction to resolve (check with /list_predictions)",
        result="The winning option"
    )
    
    async def resolve_prediction_command(self, interaction: discord.Interaction, prediction_index: int, result: str):
        await interaction.response.defer(ephemeral=True)

        if prediction_index < 0 or prediction_index >= len(self.predictions):
            await interaction.followup.send("Invalid prediction index!", ephemeral=True)
            return

        prediction = self.predictions[prediction_index]
        if prediction.resolved:
            await interaction.followup.send("This prediction has already been resolved!", ephemeral=True)
            return

        if result not in prediction.options:
            await interaction.followup.send(f"Invalid result! Available options: {', '.join(prediction.options)}", ephemeral=True)
            return

        prediction.resolve(result)
        await interaction.followup.send(f"Prediction '{prediction.question}' resolved with result: '{result}'", ephemeral=True)

        # Distribute payouts
        total_payout = prediction.get_total_bets()
        for user_id in prediction.bets[result]:
            payout = prediction.get_user_payout(user_id)
            if payout > 0:
                await self.points_manager.add_points(user_id, int(payout))

        await interaction.followup.send(f"Payouts have been distributed for prediction '{prediction.question}'!", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="bet_history", description="View bet history for a prediction")
    @app_commands.describe(
        prediction_index="The index of the prediction to view bet history (check with /list_predictions)"
    )
    async def bet_history(self, interaction: discord.Interaction, prediction_index: int):
        await interaction.response.defer(ephemeral=True)

        if prediction_index < 0 or prediction_index >= len(self.predictions):
            await interaction.followup.send("Invalid prediction index!", ephemeral=True)
            return

        prediction = self.predictions[prediction_index]
        bet_history = prediction.get_bet_history()
        if not bet_history:
            await interaction.followup.send("No bets have been placed on this prediction yet.", ephemeral=True)
            return

        history_strings = [f"User ID: {user_id}, Option: {option}, Amount: {amount:,} Points" for user_id, option, amount in bet_history]
        await interaction.followup.send("\n".join(history_strings), ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))
