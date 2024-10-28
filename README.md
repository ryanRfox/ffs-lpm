# DRIP Points System Demo
A Discord bot demonstration showcasing DRIP's points management API capabilities.

## Overview
This demo showcases the integration between Discord and DRIP's points management API. It demonstrates how easily developers can integrate DRIP's token system into their Discord applications, providing basic economy features through simple slash commands.

## Features
- **Balance Checking**: Query DRIP point balances directly through Discord
- **Tipping System**: Enable user-to-user DRIP point transfers
- **Administrative Controls**: Server management of DRIP points
- **DRIP API Integration**: Seamless connection with DRIP's token system
- **Error Handling**: Robust error checking and user feedback
- **Resource Management**: Efficient API session handling

## Setup

### Prerequisites
- Python 3.8 or higher
- Discord bot token
- DRIP API credentials

### Environment Variables
Create a `.env` file with:
```env
DISCORD_TOKEN=your_discord_bot_token
API_BASE_URL=https://api.drip.re
API_KEY=your_drip_api_key
REALM_ID=your_drip_realm_id
```

Discord token is the token of the bot, you can get one by creating an app and then generating a token. [GUIDE](https://discord.com/developers/docs/quick-start/getting-started#step-1-creating-an-app)

DRIP API key and realm ID can be found in the [DRIP API dashboard](https://dashboard.drip.re/api/extended-api).

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

## Command Usage

### User Commands
1. **Check DRIP Balance**
   ```
   /balance
   ```
   - Shows your current DRIP point balance
   - Response is private

2. **Check Other's Balance**
   ```
   /check <user>
   ```
   - Shows another user's DRIP balance

3. **Tip DRIP Points**
   ```
   /tip <user> <amount>
   ```
   - Transfer DRIP points to another user
   - Requires sufficient balance
   - Amount must be positive

### Admin Commands
1. **Add DRIP Points**
   ```
   /add_points <user> <amount>
   ```
   - Adds DRIP points to a user
   - Requires administrator permissions

2. **Remove DRIP Points**
   ```
   /remove_points <user> <amount>
   ```
   - Removes DRIP points from a user
   - Requires administrator permissions

## DRIP API Integration

### Endpoints
The demo utilizes the following DRIP API endpoints:

1. **Balance Check**
   ```
   GET /api/v4/realms/{realm_id}/members/{user_id}
   ```
   Returns user's DRIP point balance

2. **Point Modification**
   ```
   PATCH /api/v4/realms/{realm_id}/members/{user_id}/tokenBalance
   ```
   Modifies user's DRIP point balance

3. **Point Transfer**
   ```
   PATCH /api/v4/realms/{realm_id}/members/{user_id}/transfer
   ```
   Handles user-to-user DRIP point transfers

### Authentication
Uses DRIP's API key authentication:
```python
headers = {"Authorization": f"Bearer {api_key}"}
```

## Technical Implementation

### DRIP Points Manager
Implements a singleton pattern for managing DRIP API connections:
```python
class PointsManagerSingleton:
    """
    Manages DRIP API connections and point operations.
    Ensures efficient resource usage through singleton pattern.
    """
```

### Key Features
- Secure API key handling
- Efficient session management
- Comprehensive error handling
- User-friendly responses
- Permission-based access control

## Example Interactions

### Regular Users
```
/balance
> Your DRIP balance: 1,000 Points

/tip @user 100
> Successfully tipped 100 DRIP Points to @user!
```

### Administrators
```
/add_points @user 500
> Successfully added 500 DRIP Points to @user!
> Their new balance: 1,500 Points

/remove_points @user 200
> Successfully removed 200 DRIP Points from @user!
> Their new balance: 1,300 Points
```
