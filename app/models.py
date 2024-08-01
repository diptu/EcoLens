import datetime


# from enum import Enum
import enum
from sqlalchemy import (
    FLOAT,
    # Boolean,
    Column,
    Integer,
    String,
    Enum,
    TIMESTAMP,
    text,
    Enum,
)
from uuid import uuid4
from sqlalchemy.ext.hybrid import hybrid_property
from .database import Base
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


class EnergyUnit(Enum):
    KWh = "KWh"
    Wh = "Wh"


class VolumeUnit(Enum):
    L = "L"
    KL = "KL"


class AreaUnit(Enum):
    m2 = "m2"
    # km2 = "km2"


class VehicleUsages(Base):
    """The `VehicleUsages` class defines a table structure for storing VehicleUsages-related data with columns for flight distance, public transit distance, number of gasoline cars, and custom validation using enums for units."""

    __tablename__ = "vehicle_usages"
    # id = Column(
    #     Integer,
    #     primary_key=True,
    #     comment="Unique identifier",
    #     doc="Unique identifier for the VehicleUsages",
    # )
    id = Column(
        String(36),
        primary_key=True,
        default=str(uuid4()),
        comment="Unique identifier",
        doc="Unique identifier for the VehicleUsages",
    )

    flight_distance = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total flight distance VehicleUsagesed per year.",
        doc="Total flight distance VehicleUsagesed per year. Default `0`",
    )
    flight_unit = Column(
        Enum(DistanceUnit),
        server_default="Km",
        nullable=False,
        comment="Unit of measurement for flight distance..",
        doc="Unit of measurement for flight distance. Default is `Km`",
    )
    public_transit_distance = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total public transit distance VehicleUsagesed per year",
        doc="Total public transit distance VehicleUsagesed per year. Default `0`",
    )
    transit_unit = Column(
        Enum(DistanceUnit),
        server_default="Km",
        nullable=False,
        comment="Unit for public Transit",
        doc="Unit of measurement for public transit distance. Default `Km`",
    )
    num_of_gasolin_cars = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of gasoline-powered cars owned.",
        doc="Number of gasoline-powered cars owned. Default `0`",
    )
    gasoline_car_driven = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total distance VehicleUsagesed by gasoline car per year.",
        doc="Total distance VehicleUsagesed by gasoline car per year. Defaults to 0.0.",
    )
    gesoline_car_unit = Column(
        Enum(DistanceUnit),
        server_default="Km",
        nullable=False,
        comment="Unit for Gasoline Car",
        doc="Unit of measurement for gasoline car distance. Default `Km`",
    )
    num_of_diesel_cars = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of diesel-powered cars owned.",
        doc="Number of diesel-powered cars owned. Default `0`",
    )
    diesel_car_driven = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total distance VehicleUsagesed by diesel car per year.",
        doc="Total distance VehicleUsagesed by diesel car per year. Defaults to 0.0.",
    )
    diesel_car_unit = Column(
        Enum(DistanceUnit),
        server_default="Km",
        nullable=False,
        comment="Unit for Diesel Car",
        doc="Unit of measurement for diesel car distance. Default `Km`",
    )

    num_of_electric_cars = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of electric cars owned.",
        doc="Number of electric cars owned. Default `0`",
    )
    electric_car_driven = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total distance VehicleUsagesed by electric car per year.",
        doc="Total distance VehicleUsagesed by electric car per year. Defaults to 0.0.",
    )
    electric_car_unit = Column(
        Enum(DistanceUnit),
        server_default="Km",
        nullable=False,
        comment="Unit for electric Car",
        doc="Unit of measurement for electric car distance. Default `Km`",
    )

    num_of_hybrid_cars = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of hybrid cars owned.",
        doc="Number of hybrid cars owned. Default `0`",
    )
    hybrid_car_driven = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total distance VehicleUsagesed by hybrid car per year.",
        doc="Total distance VehicleUsagesed by hybrid car per year. Defaults to 0.0.",
    )
    hybrid_car_unit = Column(
        Enum(DistanceUnit),
        server_default="Km",
        nullable=False,
        comment="Unit for hybrid Car",
        doc="Unit of measurement for hybrid car distance. Default `Km`",
    )
    flight_emission = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total flight emission",
        doc="Total flight emissio",
    )
    public_transit_emission = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total Public transit emission",
        doc="Total Public transit emission",
    )
    # vehicle_usages_emission = Column(
    #     FLOAT(precision=32, decimal_return_scale=None),
    #     default=0,
    #     comment="Total vehicle usage emission",
    #     doc="Calculated vehicle usage emission",
    # )
    gasoline_car_emissions = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total Gasoline Car manufaturing emission",
        doc="Calculated Total Gasoline Car manufaturing emission",
    )
    electric_car_emissions = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total Electric Car manufaturing emission",
        doc="Calculated Total Electric Car manufaturing emission",
    )
    disel_car_emissions = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total Electric Car manufaturing emission",
        doc="Calculated Total Electric Car manufaturing emission",
    )
    hybrid_car_emissions = Column(
        FLOAT(precision=32, decimal_return_scale=None),
        default=0,
        comment="Total Hybrid Car manufaturing emission",
        doc="Calculated Total Hybrid Car manufaturing emission",
    )
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="Created timestamp",
        doc="Current timestamp",
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
        comment="Last Modified timestamp",
        doc="Last Modified in timestamp",
    )

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
