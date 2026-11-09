from internal.store import PetStore
from internal.models import PetSummary, CreatePetInput

store = PetStore()


def register_tools(server):
    server.add_tool(
        list_pets,
        name="list_pets",
        description="查询宠物档案列表，支持按种类/医生/状态筛选、关键词搜索、排序和分页",
    )
    server.add_tool(
        create_pet,
        name="create_pet",
        description="新增宠物档案，创建一个新的宠物记录",
    )


async def list_pets(
    species: str | None = None,
    doctor: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str | None = None,
    order: str | None = None,
    min_cost: float | None = None,
    max_cost: float | None = None,
) -> dict:
    """查询宠物档案列表。"""
    pets = store.list(
        species=species, doctor=doctor, status=status, keyword=keyword,
        sort_by=sort_by, order=order, min_cost=min_cost, max_cost=max_cost,
    )

    total = len(pets)
    start = (page - 1) * page_size
    end = start + page_size
    paged = pets[start:end]

    pet_summaries = [
        PetSummary(
            id=p.id, name=p.name, species=p.species, breed=p.breed,
            doctor=p.doctor, status=p.status, total_cost=p.totalCost,
            visit_count=p.visitCount,
        )
        for p in paged
    ]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pets": pet_summaries,
        "resultType": "complete",
    }


async def create_pet(
    name: str,
    species: str,
    breed: str,
    gender: str,
    ageMonths: int,
    color: str,
    ownerName: str,
    ownerPhone: str,
    doctor: str,
    disease: str,
    chipId: str | None = None,
    address: str | None = None,
    allergy: str | None = None,
    status: str = "待就诊",
) -> dict:
    """新增宠物档案。"""
    pet = store.create({
        "name": name, "species": species, "breed": breed, "gender": gender,
        "ageMonths": ageMonths, "color": color, "ownerName": ownerName,
        "ownerPhone": ownerPhone, "doctor": doctor, "disease": disease,
        "chipId": chipId, "address": address, "allergy": allergy, "status": status,
        "records": [], "charges": [],
    })

    return {
        "id": pet.id,
        "name": pet.name,
        "species": pet.species,
        "breed": pet.breed,
        "gender": pet.gender,
        "ageMonths": pet.ageMonths,
        "color": pet.color,
        "ownerName": pet.ownerName,
        "doctor": pet.doctor,
        "disease": pet.disease,
        "status": pet.status,
        "resultType": "complete",
    }
