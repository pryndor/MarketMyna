"""Mutual Fund data fetcher for Indian mutual funds."""

import pandas as pd
import requests


class MutualFundDataFetcher:
    """Fetches mutual fund data from MFAPI.in (free API for Indian MFs)."""

    BASE_URL = "https://api.mfapi.in"

    def get_historical_nav(self, scheme_code: int, days: int = 365) -> pd.DataFrame:
        """Get historical NAV data for a scheme."""
        try:
            response = requests.get(f"{self.BASE_URL}/mf/{scheme_code}", timeout=10)
            response.raise_for_status()
            data = response.json()

            nav_data = data.get("data", [])[:days]

            df = pd.DataFrame(nav_data)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y")
                df["nav"] = df["nav"].astype(float)
                df = df.sort_values("date")
                df.set_index("date", inplace=True)

            return df

        except Exception as e:
            print(f"Error fetching historical NAV for {scheme_code}: {e}")
            return pd.DataFrame()


