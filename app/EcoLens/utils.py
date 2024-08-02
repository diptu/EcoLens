# import Libraries
import enum
from .helper import ENV


class EnergyUnit(enum.Enum):
    KWh = "KWh"
    Wh = "Wh"


class VolumeUnit(enum.Enum):
    L = "L"
    KL = "KL"


class AreaUnit(enum.Enum):
    m2 = "m2"
    # km2 = "km2"


class DistanceUnit(enum.Enum):
    Km = "Km"
    Mi = "Mi"


class CarType(enum.Enum):
    E = "Electric"
    G = "Gasoline"
    D = "Diesel"
    H = "Hybrid"


# VEHICLE_EMISSION_METRICS
FLIGHT_DISTANCE_CONVERSION_FACTORS = {
    DistanceUnit.Km: ENV["FLIGHT_EMISSIONS_PER_KM"],
    DistanceUnit.Mi: 1.60934,  # TODO : MODiFY With correct value
    # Add conversion factors for other units
}

PUBLIC_TRNSIT_CONVERSION_FACTORS = {
    DistanceUnit.Km: ENV["TRANSIT_EMISSIONS_PER_KM"],
}
# Vehicle Manufacturing Emissions
GASOLINE_CAR_MANUFACTURING_EMISSIONS = {
    DistanceUnit.Km: ENV["GASOLINE_CAR_MANUFACTURING_EMISSIONS"],
}

DIESEL_CAR_MANUFACTURING_EMISSIONS = {
    DistanceUnit.Km: ENV["DIESEL_CAR_MANUFACTURING_EMISSIONS"],
}

ELECTRIC_CAR_MANUFACTURING_EMISSIONS = {
    DistanceUnit.Km: ENV["ELECTRIC_CAR_MANUFACTURING_EMISSIONS"],
}

HYBRID_CAR_MANUFACTURING_EMISSIONS = {
    DistanceUnit.Km: ENV["HYBRID_CAR_MANUFACTURING_EMISSIONS"],
}


# Car Emissions
GASOLINE_CAR_EMISSIONS_PER_KM = {
    DistanceUnit.Km: ENV["GASOLINE_CAR_EMISSIONS_PER_KM"],
}

DISEL_CAR_EMISSIONS_PER_KM = {
    DistanceUnit.Km: ENV["DISEL_CAR_EMISSIONS_PER_KM"],
}

ELECTRIC_CAR_EMISSIONS_PER_KM = {
    DistanceUnit.Km: ENV["ELECTRIC_CAR_EMISSIONS_PER_KM"],
}
HYBRID_CAR_EMISSIONS_PER_KM = {
    DistanceUnit.Km: ENV["HYBRID_CAR_EMISSIONS_PER_KM"],
}


# Residential Footprint
ELECTRICITY_CONSUMPTION_KWH = {
    DistanceUnit.Km: ENV["ELECTRICITY_CONSUMPTION_KWH"],
}


NATURAL_GAS_CONSUMPTION_KWH = {
    EnergyUnit.KWh: ENV["NATURAL_GAS_CONSUMPTION_KWH"],
}

HEATING_OIL_CONSUMPTION_LITRE = {
    VolumeUnit.L: ENV["HEATING_OIL_CONSUMPTION_LITRE"],
}

WATER_USAGES_LITRE = {
    VolumeUnit.L: ENV["WATER_USAGES_LITRE"],
}
LIVING_SPACE_CONSTRUCTION_EMISSION_M2 = {
    AreaUnit.m2: ENV["LIVING_SPACE_CONSTRUCTION_EMISSION_M2"],
}
