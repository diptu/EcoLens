from datetime import datetime
from pydantic import BaseModel, Field, computed_field
from enum import Enum
from typing import Optional
from .utils import (
    DistanceUnit,
    FLIGHT_DISTANCE_CONVERSION_FACTORS,
    PUBLIC_TRNSIT_CONVERSION_FACTORS,
    GASOLINE_CAR_MANUFACTURING_EMISSIONS,
    DIESEL_CAR_MANUFACTURING_EMISSIONS,
    ELECTRIC_CAR_MANUFACTURING_EMISSIONS,
    HYBRID_CAR_MANUFACTURING_EMISSIONS,
    GASOLINE_CAR_EMISSIONS_PER_KM,
    DISEL_CAR_EMISSIONS_PER_KM,
    ELECTRIC_CAR_EMISSIONS_PER_KM,
    HYBRID_CAR_EMISSIONS_PER_KM,
)


def convert_to_si_units(value):
    pass


def convert_to_imperical_units(value):
    pass


class EnergyUnit(str, Enum):
    Wh = "Wh"
    KWh = "KWh"


class VolumeUnit(str, Enum):
    L = "L"
    KL = "KL"


class AreaUnit(str, Enum):
    m2 = "m2"
    # km2 = "km2"


class VehicleUsages(BaseModel):
    # id: int = Field(description="unique identifier")
    flight_distance: float = Field(
        ge=0, description="Total flight distance VehicleUsagesed per year.", default=0
    )
    flight_unit: Optional[DistanceUnit] = Field(
        default="Km",
        description="Unit of measurement for flight distance.",
    )
    public_transit_distance: float = Field(
        ge=0,
        description="Total public transit distance VehicleUsagesed per year",
        default=0,
    )
    transit_unit: Optional[DistanceUnit] = Field(
        default="Km",
        description="Unit of measurement for public transit distance.",
    )
    num_of_gasolin_cars: int = Field(
        ge=0, default=0, description="Number of gasoline-powered cars owned."
    )
    num_of_gasolin_cars: int = Field(
        ge=0, default=0, description="Number of gasoline-powered cars owned."
    )
    gasoline_car_driven: float = Field(
        ge=0,
        description="Total distance VehicleUsagesed by gasoline car per year",
        default=0,
    )
    gesoline_car_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for gasoline car distance. Default `Km`",
    )
    num_of_diesel_cars: int = Field(
        ge=0, default=0, description="Number of diesel-powered cars owned."
    )
    diesel_car_driven: float = Field(
        ge=0,
        description="Total distance VehicleUsagesed by diesel car per year",
        default=0,
    )
    diesel_car_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for diesel car distance. Default `Km`",
    )
    num_of_electric_cars: int = Field(
        ge=0, default=0, description="Number of electric cars owned."
    )
    electric_car_driven: float = Field(
        ge=0,
        description="Total distance VehicleUsagesed by electric car per year",
        default=0,
    )
    electric_car_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for electric car distance. Default `Km`",
    )

    num_of_hybrid_cars: int = Field(
        ge=0, default=0, description="Number of hybrid cars owned."
    )
    hybrid_car_driven: float = Field(
        ge=0,
        description="Total distance VehicleUsagesed by hybrid car per year",
        default=0,
    )
    hybrid_car_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for hybrid car distance. Default `Km`",
    )

    # Calculated/Derived Fields
    flight_emission: float = Field(
        ge=0,
        description="Converted total flight usages emission per year",
        default=0,
    )
    public_transit_emission: float = Field(
        ge=0,
        description="Converted public transit usages emission per year",
        default=0,
    )

    gasoline_car_emissions: float = Field(
        ge=0,
        description="Calculated Total Gasoline Car manufaturing emission",
        default=0,
    )
    electric_car_emissions: float = Field(
        ge=0,
        description="Calculated Total Electric Car manufaturing emission",
        default=0,
    )
    disel_car_emissions: float = Field(
        ge=0,
        description="Calculated Total Electric Car manufaturing emission",
        default=0,
    )
    hybrid_car_emissions: float = Field(
        ge=0,
        description="Calculated Total Electric Car manufaturing emission",
        default=0,
    )
    # vehicle_usages_emission: float = Field(
    #     ge=0,
    #     description="Total vehicle usages emission per year",
    #     default=0,
    # )

    # def __init__(self, **data):
    #     super().__init__(**data)

    def calculate_derived_fields(self):
        self.flight_emission = (
            self.flight_distance * FLIGHT_DISTANCE_CONVERSION_FACTORS[self.flight_unit]
        )
        self.public_transit_emission = (
            self.public_transit_distance
            * PUBLIC_TRNSIT_CONVERSION_FACTORS[self.transit_unit]
        )
        self.gasoline_car_emissions = (
            self.gasoline_car_driven
            * GASOLINE_CAR_EMISSIONS_PER_KM[self.gesoline_car_unit]
        ) + GASOLINE_CAR_MANUFACTURING_EMISSIONS[self.gesoline_car_unit]

        self.disel_car_emissions = (
            self.diesel_car_driven * DISEL_CAR_EMISSIONS_PER_KM[self.diesel_car_unit]
        ) + DIESEL_CAR_MANUFACTURING_EMISSIONS[self.diesel_car_unit]

        self.electric_car_emissions = (
            ELECTRIC_CAR_EMISSIONS_PER_KM[self.electric_car_unit]
            * self.electric_car_driven
        ) + ELECTRIC_CAR_MANUFACTURING_EMISSIONS[self.electric_car_unit]
        self.hybrid_car_emissions = (
            HYBRID_CAR_EMISSIONS_PER_KM[self.hybrid_car_unit] * self.hybrid_car_driven
        ) + HYBRID_CAR_MANUFACTURING_EMISSIONS[self.hybrid_car_unit]

        # # TODO: Update this Logic later
        # self.vehicle_usages_emission = (
        #     self.flight_emission + self.public_transit_emission
        # )


class VehicleUsagesView(BaseModel):
    """`VehicleUsagesView` model is used for data validation and serialization/deserialization in Python."""

    # id: int = Field(description="unique identifier")
    flight_distance: float = Field(
        ge=0, description="Total flight distance traveled per year.", default=0
    )
    flight_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for flight distance. default is `Km`",
    )
    public_transit_distance: float = Field(
        ge=0, description="Total public transit distance traveled per year", default=0
    )
    transit_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for public transit distance. Default is `Km`",
    )
    num_of_gasolin_cars: int = Field(
        ge=0, default=0, description="Number of gasoline-powered cars owned."
    )
    gasoline_car_driven: float = Field(
        ge=0, description="Total distance traveled by gasoline car per year", default=0
    )
    gesoline_car_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for gasoline car distance. Default `Km`",
    )
    num_of_diesel_cars: int = Field(
        ge=0, default=0, description="Number of diesel-powered cars owned."
    )
    diesel_car_driven: float = Field(
        ge=0, description="Total distance traveled by diesel car per year", default=0
    )
    diesel_car_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for diesel car distance. Default `Km`",
    )
    num_of_electric_cars: int = Field(
        ge=0, default=0, description="Number of electric cars owned."
    )
    electric_car_driven: float = Field(
        ge=0, description="Total distance traveled by electric car per year", default=0
    )
    electric_car_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for electric car distance. Default `Km`",
    )

    num_of_hybrid_cars: int = Field(
        ge=0, default=0, description="Number of hybrid cars owned."
    )
    hybrid_car_driven: float = Field(
        ge=0, description="Total distance traveled by hybrid car per year", default=0
    )
    hybrid_car_unit: Optional[DistanceUnit] = Field(
        default=DistanceUnit.Km,
        description="Unit of measurement for hybrid car distance. Default `Km`",
    )

    class Config:
        # orm_mode = True
        from_attributes = True
