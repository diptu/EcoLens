import os
from typing import List
from fastapi import Depends, FastAPI, HTTPException, Request, status, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import models, schemas
from .database import SessionLocal, engine, get_db

models.Base.metadata.create_all(bind=engine)
app = FastAPI()


# script_dir = os.path.dirname(__file__)
# static_abs_file_path = os.path.join(script_dir, "static/")
# template_dir = os.path.join(script_dir, "templates/")
# app.mount("/static", StaticFiles(directory=static_abs_file_path), name="static")
# templates = Jinja2Templates(directory=template_dir)


# @app.get("/", response_class=HTMLResponse)
# async def Home(request: Request):
#     return templates.TemplateResponse(
#         request=request,
#         name="home.html",
#         context={"title": "Home"},
#     )


@app.get(
    "/emission/household_emission/vehicle_usage_metrics",
    response_model=List[schemas.VehicleUsagesView],
    status_code=200,
)
async def get_vehicle_usage_metrics(
    response: Response,
    db: Session = Depends(get_db),
):
    items = db.query(models.VehicleUsages).all()
    if not items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle Usage Metrics are not available",
        )
    return items


@app.post(
    "/emission/household_emission/vehicle_usage_metrics",
    status_code=201,
    response_model=schemas.VehicleUsagesView,
)
async def create(
    request: schemas.VehicleUsagesView,
    response: Response,
    db: Session = Depends(get_db),
):
    new_item = models.VehicleUsages(
        flight_distance=request.flight_distance,
        flight_unit=request.flight_unit,
        public_transit_distance=request.public_transit_distance,
        transit_unit=request.transit_unit,
        num_of_gasolin_cars=request.num_of_gasolin_cars,
        gasoline_car_driven=request.gasoline_car_driven,
        gesoline_car_unit=request.gesoline_car_unit,
        num_of_diesel_cars=request.num_of_diesel_cars,
        diesel_car_driven=request.diesel_car_driven,
        diesel_car_unit=request.diesel_car_unit,
        num_of_electric_cars=request.num_of_electric_cars,
        electric_car_driven=request.electric_car_driven,
        electric_car_unit=request.electric_car_unit,
        num_of_hybrid_cars=request.num_of_hybrid_cars,
        hybrid_car_driven=request.hybrid_car_driven,
        hybrid_car_unit=request.hybrid_car_unit,
    )
    new_item.calculate_derived_fields()
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    response.status_code = status.HTTP_201_CREATED
    return {
        "data": new_item,
        "details": "Vehicle Usage Metrics created successfully",
    }


@app.get(
    "/emission/household_emission/vehicle_usage_metrics/{id}",
    response_model=schemas.VehicleUsagesView,
    status_code=200,
)
async def get_vehicle_usage_metrics_by_id(
    id: str, response: Response, db: Session = Depends(get_db)
):
    new_item = (
        db.query(models.VehicleUsages).filter(models.VehicleUsages.id == id).first()
    )
    if not new_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle Usage Metrics with id:{id} not available",
        )
    return new_item


@app.delete(
    "/emission/household_emission/vehicle_usage_metrics/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_vehicle_usage_metrics(
    id: str, response: Response, db: Session = Depends(get_db)
):
    item = db.query(models.VehicleUsages).filter(models.VehicleUsages.id == id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle Usage Metrics with id:{id} not available",
        )
    item.delete(synchronize_session=False)
    db.commit()
    return {"detail": f"Vehicle Usage Metrics with id:{id} deleted successfully"}


@app.patch("/emission/household_emission/vehicle_usage_metrics/{id}", status_code=200)
def update_vehicle_usage_metrics(
    id: str,
    request: schemas.VehicleUsagesView,
    db: Session = Depends(get_db),
):
    """Use this method to partialy update the vehicle usage metrics"""
    new_item = (
        db.query(models.VehicleUsages).filter(models.VehicleUsages.id == id).first()
    )
    if not new_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle Usage Metrics with id:{id} not available",
        )

    # Update existing object with data from request schema
    for key, value in request.model_dump(exclude_unset=True).items():
        print(f"Keys:{key}, value:{value}")
        setattr(new_item, key, value)

    # TODO: Update existing Logic
    new_item.calculate_derived_fields()
    db.commit()
    # Refresh the object to get updated data (optional)
    db.refresh(new_item)
    return {"message": f"Vehicle Usage Metrics with id:{id} updated successfully"}


# @app.post("/emission/household_emission/home")
# async def create_home_emission(
#     request: schemas.HomeView, db: Session = Depends(get_db)
# ):
#     new_home = models.Home(
#         electricity_consumption=request.electricity_consumption,
#         consumption_unit=request.consumption_unit,
#         natural_gas_consumption=request.natural_gas_consumption,
#         gas_consumption_unit=request.gas_consumption_unit,
#         water_usage=request.water_usage,
#         # water_usage_unit = request.water_usage_unit,
#         living_space=request.living_space,
#         # living_space_unit = living_space_unit,
#     )
#     db.add(new_home)
#     db.commit()
#     db.refresh(new_home)
#     return new_home
