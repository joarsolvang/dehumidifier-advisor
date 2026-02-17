"""Octopus Energy UK API client."""

import logging
from datetime import datetime
from typing import Any, ClassVar

import httpx

from octopus_energy_uk_api.models import AgileRates, AgileRatesTimeSeries, StandingCharge, UnitRate

logger = logging.getLogger(__name__)


class OctopusEnergyError(Exception):
    """Base exception for Octopus Energy API errors."""


class ProductNotFoundError(OctopusEnergyError):
    """Raised when a product code is not found."""


class TariffNotFoundError(OctopusEnergyError):
    """Raised when a tariff code is not found."""


class OctopusEnergyClient:
    """Client for the Octopus Energy UK public API (Agile tariff pricing).

    Methods that accept a ``gsp`` parameter expect a single-letter Grid Supply Point
    region code. GSPs are the 14 regions of the UK electricity grid, each with
    independent wholesale pricing. The mapping is:

        A = South East England
        B = East Midlands
        C = East England
        D = Merseyside & North Wales
        E = West Midlands
        F = North East England
        G = North West England
        H = Southern England
        J = South East England (second zone)
        K = South Wales
        L = South West England
        M = Yorkshire
        N = South Scotland
        P = North Scotland
    """

    BASE_URL: ClassVar[str] = "https://api.octopus.energy/v1"

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def _paginate(self, url: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """Fetch all pages of a paginated API response."""
        results: list[dict[str, Any]] = []
        page = 1
        try:
            with httpx.Client(timeout=self.timeout) as client:
                while url:
                    logger.debug("Fetching page %d: %s params=%s", page, url, params)
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()
                    page_results = data.get("results", [])
                    results.extend(page_results)
                    logger.debug("Page %d returned %d results", page, len(page_results))
                    url = data.get("next") or ""
                    params = {}  # next URL includes query params
                    page += 1
        except httpx.ConnectError as e:
            msg = f"Cannot connect to Octopus Energy API: {e}"
            logger.error(msg)
            raise OctopusEnergyError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Octopus Energy API error: {e.response.status_code} - {e.response.text}"
            logger.error(msg)
            raise OctopusEnergyError(msg) from e
        except httpx.HTTPError as e:
            msg = f"HTTP error communicating with Octopus Energy API: {e}"
            logger.error(msg)
            raise OctopusEnergyError(msg) from e
        logger.debug("Pagination complete: %d total results across %d pages", len(results), page - 1)
        return results

    def get_product(self, product_code: str) -> dict[str, Any]:
        """Get full product detail (raw dict, since the response is complex/nested)."""
        url = f"{self.BASE_URL}/products/{product_code}/"
        logger.info("Fetching product detail: %s", product_code)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url)
                response.raise_for_status()
                logger.debug("Product detail retrieved for %s", product_code)
                return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                msg = f"Product not found: {product_code}"
                logger.warning(msg)
                raise ProductNotFoundError(msg) from e
            msg = f"Octopus Energy API error: {e.response.status_code} - {e.response.text}"
            logger.error(msg)
            raise OctopusEnergyError(msg) from e
        except httpx.ConnectError as e:
            msg = f"Cannot connect to Octopus Energy API: {e}"
            logger.error(msg)
            raise OctopusEnergyError(msg) from e
        except httpx.HTTPError as e:
            msg = f"HTTP error communicating with Octopus Energy API: {e}"
            logger.error(msg)
            raise OctopusEnergyError(msg) from e

    def get_agile_tariff_code(self, product_code: str, *, gsp: str = "A") -> str:
        """Extract the electricity tariff code for a GSP region from a product."""
        logger.info("Resolving tariff code for product=%s gsp=%s", product_code, gsp)
        product = self.get_product(product_code)
        tariffs = product.get("single_register_electricity_tariffs", {})
        gsp_key = f"_{gsp}"
        region_tariffs = tariffs.get(gsp_key)
        if not region_tariffs:
            msg = f"No electricity tariff found for GSP region '{gsp}' in product '{product_code}'"
            logger.warning(msg)
            raise TariffNotFoundError(msg)
        direct_debit = region_tariffs.get("direct_debit_monthly", {})
        tariff_code = direct_debit.get("code", "")
        if not tariff_code:
            msg = f"No tariff code found for GSP region '{gsp}' in product '{product_code}'"
            logger.warning(msg)
            raise TariffNotFoundError(msg)
        logger.info("Resolved tariff code: %s", tariff_code)
        return tariff_code  # type: ignore[no-any-return]

    def get_unit_rates(
        self,
        product_code: str,
        tariff_code: str,
        *,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> list[UnitRate]:
        """Fetch unit rates for a tariff, auto-paginates."""
        url = f"{self.BASE_URL}/products/{product_code}/electricity-tariffs/{tariff_code}/standard-unit-rates/"
        logger.info("Fetching unit rates for tariff=%s", tariff_code)
        params: dict[str, str] = {}
        if period_from is not None:
            params["period_from"] = period_from.isoformat()
        if period_to is not None:
            params["period_to"] = period_to.isoformat()

        results = self._paginate(url, params)
        logger.info("Fetched %d unit rates", len(results))
        return [UnitRate.model_validate(r) for r in results]

    def get_standing_charges(
        self,
        product_code: str,
        tariff_code: str,
        *,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> list[StandingCharge]:
        """Fetch standing charges for a tariff."""
        url = f"{self.BASE_URL}/products/{product_code}/electricity-tariffs/{tariff_code}/standing-charges/"
        logger.info("Fetching standing charges for tariff=%s", tariff_code)
        params: dict[str, str] = {}
        if period_from is not None:
            params["period_from"] = period_from.isoformat()
        if period_to is not None:
            params["period_to"] = period_to.isoformat()

        results = self._paginate(url, params)
        logger.info("Fetched %d standing charges", len(results))
        return [StandingCharge.model_validate(r) for r in results]

    def get_agile_rates(
        self,
        product_code: str,
        *,
        gsp: str = "A",
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> AgileRates:
        """Convenience method: resolve tariff, fetch unit rates and standing charges."""
        logger.info("Fetching agile rates for product=%s gsp=%s", product_code, gsp)
        tariff_code = self.get_agile_tariff_code(product_code, gsp=gsp)
        unit_rates = self.get_unit_rates(product_code, tariff_code, period_from=period_from, period_to=period_to)
        standing_charges = self.get_standing_charges(
            product_code, tariff_code, period_from=period_from, period_to=period_to
        )
        return AgileRates(
            tariff_code=tariff_code,
            product_code=product_code,
            unit_rates=unit_rates,
            standing_charges=standing_charges,
        )

    def get_agile_rates_timeseries(
        self,
        product_code: str,
        *,
        gsp: str = "A",
        period_from: datetime | None = None,
        period_to: datetime | None = None,
    ) -> AgileRatesTimeSeries:
        """Fetch Agile rates and convert to a flat timeseries.

        Each unit rate covers a half-hour window [valid_from, valid_to).
        """
        rates = self.get_agile_rates(product_code, gsp=gsp, period_from=period_from, period_to=period_to)
        product = self.get_product(product_code)
        sorted_rates = sorted(rates.unit_rates, key=lambda r: r.valid_from)
        timestamps = [r.valid_from.isoformat() for r in sorted_rates]
        values = [r.value_inc_vat for r in sorted_rates]

        return AgileRatesTimeSeries(
            name=f"Agile unit rate ({rates.tariff_code})",
            desciption=product.get("description", product_code),
            timestamps=timestamps,
            timestamp_format="ISO 8601",
            timezone="UTC",
            values=values,
            values_unit="p/kWh",
        )
