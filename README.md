# Discord Prediction Market Bot

A Discord bot that enables server members to create and participate in prediction markets using a points-based system. Users can create predictions, place bets on different outcomes, and win points based on correct predictions.

## Features

- Create prediction markets with multiple options
- Place bets on active predictions
- Automatic market closure and resolution system
- Category-based organization
- Odds calculation and display
- Automatic refund system for unresolved predictions
- User notifications for bet outcomes

## Commands

### `/create_prediction`
Creates a new prediction market.
- Parameters:
  - `question`: The main question or topic of the prediction
  - `duration`: How long the prediction will remain open (in minutes)
  - `options`: Comma-separated list of possible outcomes
  - `category` (optional): Category to organize predictions

Example:
```
/create_prediction question:"Will it rain tomorrow?" duration:1440 options:"Yes,No" category:"Weather"
```
### `/bet`
Place a bet on an active prediction.
1. Select a category
2. Choose a prediction
3. Select an option to bet on
4. Enter the amount to bet

The bot will show current odds and your potential payout before confirming the bet.

### `/list_predictions`
Displays all predictions, organized into categories:
- 🟢 Active Markets: Currently open for betting
- 🟡 Pending Resolution: Betting closed, awaiting resolution
- ⭐ Resolved Markets: Completed predictions with results
- 💰 Refunded Markets: Predictions that were refunded

Each prediction shows:
- Question
- Category
- Total betting pool
- Current odds
- Time remaining/ended
- Winner (for resolved predictions)

### `/resolve_prediction`
Resolve a prediction by selecting the winning outcome.
- Only available to the prediction creator
- Must be used within 48 hours of prediction end time
- Automatically distributes winnings to successful bettors

## Automatic Features

### Market Closure
- Markets automatically close after the specified duration
- Creator is notified when betting period ends
- Creator has 48 hours to resolve the prediction

### Refund System
- If a prediction isn't resolved within 48 hours of closing:
  - All bets are automatically refunded
  - Users are notified of the refund
  - Market is marked as refunded

### Notifications
Users receive direct messages for:
- Winning bets (showing profit and total payout)
- Losing bets (showing amount lost)
- Refunded bets
- Market resolution requirements (for creators)

## Points System
- Users must have sufficient points to place bets
- Winning payouts are calculated based on odds
- Points are automatically transferred when:
  - Placing bets
  - Receiving winnings
  - Getting refunds

## Best Practices

### Creating Predictions
- Use clear, unambiguous questions
- Provide distinct, mutually exclusive options
- Set appropriate durations for the type of prediction
- Use categories to organize related predictions

### Betting
- Check current odds before betting
- Consider the total pool size
- Monitor remaining time before market closure
- Review your betting history to improve strategy

### Resolution
- Resolve predictions promptly after the outcome is known
- Ensure fair and accurate resolution based on verifiable results
- Consider setting up clear resolution criteria when creating predictions

## Notes
- All times are displayed in UTC
- Odds are updated in real-time as bets are placed
- Bot requires administrator permissions to manage predictions
## Setup

### Prerequisites
- Python 3.8 or higher
- Discord bot token
- DRIP API credentials

### Environment Variables
Create a `.env` file with:
```env
TOKEN=your_discord_bot_token
API_BASE_URL=https://api.drip.re
API_KEY=your_drip_api_key
REALM_ID=your_drip_realm_id
```

Discord token is the token of the bot, you can get one by creating an app and then generating a token. [GUIDE](https://discord.com/developers/docs/quick-start/getting-started#step-1-creating-an-app)

DRIP API key and realm ID can be found in your DRIP Admin channel in the server you want to use.

### Installation
1. Clone the repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Configure environment variables
4. Run the bot:
```bash
python bot.py
```