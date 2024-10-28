import aiohttp
from typing import Optional

class PointsManagerSingleton:
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, base_url: str = None, api_key: str = None, realm_id: str = None):
        if not self._initialized and all([base_url, api_key, realm_id]):
            self.base_url = base_url.rstrip('/')
            self.api_key = api_key
            self.realm_id = realm_id
            self.session: Optional[aiohttp.ClientSession] = None
            self._initialized = True
    
    async def initialize(self):
        """Initialize the aiohttp session if it doesn't exist."""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def cleanup(self):
        """Cleanup the aiohttp session."""
        if self.session:
            await self.session.close()
            self.session = None

    async def _get_headers(self) -> dict:
        """Get headers with API key authentication."""
        return {"Authorization": f"Bearer {self.api_key}"}

    async def get_balance(self, user_id: int) -> int:
        """Get the point balance for a user."""
        if not self.session:
            await self.initialize()
            
        headers = await self._get_headers()
        
        async with self.session.get(
            f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{user_id}",
            headers=headers
        ) as response:
            if response.status == 200:
                data = await response.json()
                if not data.get('balances'):
                    return 0
                realm_point_ids = list(data['balances'].keys())
                return data['balances'].get(realm_point_ids[0], 0)
            else:
                error_data = await response.json()
                raise Exception(f"Failed to get balance: {error_data}")

    async def add_points(self, user_id: int, amount: int) -> bool:
        """Add points to a user's balance."""
        if not self.session:
            await self.initialize()
            
        headers = await self._get_headers()
        
        async with self.session.patch(
            f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{user_id}/tokenBalance",
            headers=headers,
            json={"tokens": amount}
        ) as response:
            return response.status == 200

    async def remove_points(self, user_id: int, amount: int) -> bool:
        """Remove points from a user's balance."""
        return await self.add_points(user_id, -amount)

    async def transfer_points(self, from_user_id: int, to_user_id: int, amount: int) -> bool:
        """Transfer points from one user to another."""
        if not self.session:
            await self.initialize()
            
        headers = await self._get_headers()
        
        async with self.session.patch(
            f"{self.base_url}/api/v4/realms/{self.realm_id}/members/{from_user_id}/transfer",
            headers=headers,
            json={
                "recipientId": to_user_id,
                "tokens": amount
            }
        ) as response:
            return response.status == 200