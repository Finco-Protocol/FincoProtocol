"""Thin provider clients; quote/calldata generation only."""
import os
import httpx

class EnsoClient:
    base_url="https://api.enso.finance/api/v1"
    def __init__(self, api_key=None, client=None):
        self.api_key=api_key or os.getenv("ENSO_API_KEY"); self.client=client or httpx.Client(timeout=15)
    @property
    def configured(self): return bool(self.api_key)
    def route(self, params: dict)->dict:
        if not self.api_key: raise RuntimeError("ENSO_API_KEY is unavailable")
        r=self.client.get(f"{self.base_url}/shortcuts/route",params=params,headers={"Authorization":f"Bearer {self.api_key}"})
        r.raise_for_status(); return r.json()

class ZeroXClient:
    base_url="https://api.0x.org"
    def __init__(self, api_key=None, client=None):
        self.api_key=api_key or os.getenv("ZERO_X_API_KEY"); self.client=client or httpx.Client(timeout=15)
    @property
    def configured(self): return bool(self.api_key)
    def quote(self, *, chain_id:int,sell_token:str,buy_token:str,sell_amount:int,taker:str)->dict:
        if not self.api_key: raise RuntimeError("ZERO_X_API_KEY is unavailable")
        r=self.client.get(f"{self.base_url}/swap/allowance-holder/quote",params={"chainId":chain_id,"sellToken":sell_token,"buyToken":buy_token,"sellAmount":str(sell_amount),"taker":taker},headers={"0x-api-key":self.api_key,"0x-version":"v2"})
        r.raise_for_status(); return r.json()
