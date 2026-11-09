from pydantic import BaseModel, Field
from typing import Optional


class Pet(BaseModel):
    id: str
    name: str
    species: str
    breed: str
    gender: str
    ageMonths: int
    color: str
    chipId: Optional[str] = None
    ownerName: str
    ownerPhone: str
    address: Optional[str] = None
    doctor: str
    disease: str
    status: str
    allergy: Optional[str] = None
    records: list[dict]
    charges: list[dict]
    totalCost: float = 0.0
    visitCount: int = 0


class CreatePetInput(BaseModel):
    name: str = Field(..., description="宠物姓名")
    species: str = Field(..., description="种类（犬、猫、兔等）")
    breed: str = Field(..., description="品种")
    gender: str = Field(..., description="性别（公/母）")
    ageMonths: int = Field(..., ge=0, description="月龄")
    color: str = Field(..., description="毛色")
    ownerName: str = Field(..., description="主人姓名")
    ownerPhone: str = Field(..., description="电话")
    doctor: str = Field(..., description="主治医生")
    disease: str = Field(..., description="疾病")
    chipId: Optional[str] = Field(default=None, description="芯片号")
    address: Optional[str] = Field(default=None, description="住址")
    allergy: Optional[str] = Field(default=None, description="过敏史")
    status: str = Field(default="待就诊", description="就诊状态")


class Record(BaseModel):
    doctor: str
    diagnosis: str
    symptoms: str
    treatment: str
    prescription: list[str]
    charge: float
    date: str


class Charge(BaseModel):
    item: str
    category: str
    amount: float
    doctor: str
    date: str


class PetSummary(BaseModel):
    id: str
    name: str
    species: str
    breed: str
    doctor: str
    status: str
    total_cost: float
    visit_count: int


class ListPetsOutput(BaseModel):
    total: int
    page: int
    page_size: int
    pets: list[PetSummary]
