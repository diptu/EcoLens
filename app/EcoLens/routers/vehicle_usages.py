from fastapi import APIRouter
from typing import List
from fastapi import Depends, FastAPI, HTTPException, Request, status, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from EcoLens import models, schemas
from EcoLens.database import SessionLocal, engine, get_db
from ..repository import vehicle_usages

router = APIRouter(
    prefix="/emission/vehicle_usage_metrics",
    tags=["VehicleUsage"],
)


# Create VehicleUsagesView
@router.post(
    "/",
    status_code=status.HTTP_200_OK,
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


# Read VehicleUsagesView
@router.get(
    "/",
    response_model=List[schemas.VehicleUsagesView],
    status_code=status.HTTP_200_OK,
)
async def read(
    response: Response,
    db: Session = Depends(get_db),
):
    items = db.query(models.VehicleUsages).all()
    if not items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle Usage Metrics are not available",
        )
    response.status_code = status.HTTP_200_OK
    return items


# Read VehicleUsagesView
@router.get(
    "/{id}",
    response_model=schemas.VehicleUsagesView,
    status_code=status.HTTP_200_OK,
)
async def read_by_id(id: int, db: Session = Depends(get_db)):
    new_item = (
        db.query(models.VehicleUsages).filter(models.VehicleUsages.id == id).first()
    )
    if not new_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle Usage Metrics with id:{id} not available",
        )
    status_code = status.HTTP_200_OK
    return new_item


# Update VehicleUsagesView
@router.patch(
    "/{id}",
    status_code=status.HTTP_200_OK,
)
def update(
    id: int,
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
    status_code = status.HTTP_202_ACCEPTED
    return {"message": f"Vehicle Usage Metrics with id:{id} updated successfully"}


# Delete VehicleUsagesView
@router.delete(
    "/{id}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete(
    id: int,
    # response: Response,
    db: Session = Depends(get_db),
):
    item = db.query(models.VehicleUsages).filter(models.VehicleUsages.id == id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle Usage Metrics with id:{id} not available",
        )
    item.delete(synchronize_session=False)
    db.commit()
    status_code = status.HTTP_204_NO_CONTENT
    return {"detail": f"Vehicle Usage Metrics with id:{id} deleted successfully"}
