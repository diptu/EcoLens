import os
from dotenv import load_dotenv

# Specify the path to your environment file
dotenv_path = os.path.join(
    os.path.dirname(__file__), "environment", ".vehicle_usages_env"
)


def load_env_vars(path):
    """Loads environment variables from .env file into a dictionary."""
    load_dotenv(path)
    env_vars = {
        "FLIGHT_EMISSIONS_PER_KM": float(
            os.getenv("FLIGHT_EMISSIONS_PER_KM"),
        ),
        "TRANSIT_EMISSIONS_PER_KM": float(
            os.getenv("TRANSIT_EMISSIONS_PER_KM"),
        ),
        "GASOLINE_CAR_MANUFACTURING_EMISSIONS": float(
            os.getenv("GASOLINE_CAR_MANUFACTURING_EMISSIONS")
        ),
        "DIESEL_CAR_MANUFACTURING_EMISSIONS": float(
            os.getenv("DIESEL_CAR_MANUFACTURING_EMISSIONS"),
        ),
        "ELECTRIC_CAR_MANUFACTURING_EMISSIONS": float(
            os.getenv("ELECTRIC_CAR_MANUFACTURING_EMISSIONS"),
        ),
        "HYBRID_CAR_MANUFACTURING_EMISSIONS": float(
            os.getenv("HYBRID_CAR_MANUFACTURING_EMISSIONS"),
        ),
        "GASOLINE_CAR_EMISSIONS_PER_KM": float(
            os.getenv("GASOLINE_CAR_EMISSIONS_PER_KM"),
        ),
        "DISEL_CAR_EMISSIONS_PER_KM": float(
            os.getenv("DISEL_CAR_EMISSIONS_PER_KM"),
        ),
        "ELECTRIC_CAR_EMISSIONS_PER_KM": float(
            os.getenv("ELECTRIC_CAR_EMISSIONS_PER_KM"),
        ),
        "HYBRID_CAR_EMISSIONS_PER_KM": float(
            os.getenv("HYBRID_CAR_EMISSIONS_PER_KM"),
        ),
        "ELECTRICITY_CONSUMPTION_KWH": float(
            os.getenv("ELECTRICITY_CONSUMPTION_KWH"),
        ),
        "NATURAL_GAS_CONSUMPTION_KWH": float(
            os.getenv("NATURAL_GAS_CONSUMPTION_KWH"),
        ),
        "HEATING_OIL_CONSUMPTION_LITRE": float(
            os.getenv("HEATING_OIL_CONSUMPTION_LITRE"),
        ),
        "WATER_USAGES_LITRE": float(
            os.getenv("WATER_USAGES_LITRE"),
        ),
        "LIVING_SPACE_CONSTRUCTION_EMISSION_M2": float(
            os.getenv("LIVING_SPACE_CONSTRUCTION_EMISSION_M2"),
        ),
    }
    return env_vars


# Example usage:
ENV = load_env_vars(dotenv_path)
flight_emissions = ENV["FLIGHT_EMISSIONS_PER_KM"]
print(flight_emissions)
