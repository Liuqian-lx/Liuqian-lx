import struct
import zlib
import json
from typing import Optional
from internal.models import Pet


class PetStore:
    """解析 pet.db 文件，维护内存索引。"""

    def __init__(self, db_path: str = "./data/pet.db"):
        self.db_path = db_path
        self.pets: dict[str, Pet] = {}
        self._load()

    def _load(self):
        with open(self.db_path, "rb") as f:
            header = f.read(32)
            magic = header[:8].decode().strip()
            if magic != "PETDBv1":
                raise ValueError(f"Unknown database format: {magic}")
            version = struct.unpack('<I', header[8:12])[0]
            flags = struct.unpack('<I', header[12:16])[0]

            while True:
                raw_len = f.read(4)
                if not raw_len or len(raw_len) < 4:
                    break
                rec_len = struct.unpack('<I', raw_len)[0]
                crc = struct.unpack('<I', f.read(4))[0]
                payload = f.read(rec_len)

                if zlib.crc32(payload) != crc:
                    break

                rec = json.loads(payload.decode('utf-8'))
                if rec.get("op") == "put":
                    pet = Pet(**rec["data"])
                    pet.totalCost = sum(c.get("amount", 0) for c in pet.charges)
                    pet.visitCount = len(pet.records)
                    self.pets[pet.id] = pet
                elif rec.get("op") == "del":
                    self.pets.pop(rec["id"], None)

    def _append_record(self, rec: dict):
        payload = json.dumps(rec, ensure_ascii=False).encode('utf-8')
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        with open(self.db_path, "ab") as f:
            f.write(struct.pack('<I', len(payload)))
            f.write(struct.pack('<I', crc))
            f.write(payload)

    def create(self, data: dict) -> Pet:
        existing_ids = [int(p.id.split('-')[1]) for p in self.pets.values() if p.id.startswith('PET-')]
        next_id = max(existing_ids) + 1 if existing_ids else 1
        pet_id = f"PET-{next_id:06d}"

        pet_data = {**data}
        pet_data['id'] = pet_id
        pet_data.setdefault('records', [])
        pet_data.setdefault('charges', [])
        pet_data.setdefault('totalCost', 0.0)
        pet_data.setdefault('visitCount', 0)

        pet = Pet(**pet_data)
        pet.totalCost = sum(c.get("amount", 0) for c in pet.charges)
        pet.visitCount = len(pet.records)

        self._append_record({"op": "put", "id": pet_id, "data": pet_data})
        self.pets[pet_id] = pet
        return pet

    def list(self, **filters) -> list[Pet]:
        results = list(self.pets.values())
        if filters.get("species"):
            results = [p for p in results if p.species == filters["species"]]
        if filters.get("doctor"):
            results = [p for p in results if p.doctor == filters["doctor"]]
        if filters.get("status"):
            results = [p for p in results if p.status == filters["status"]]
        if filters.get("keyword"):
            kw = filters["keyword"].lower()
            def _match_keyword(p):
                fields = [str(getattr(p, f, "")) for f in ["name", "species", "breed", "doctor", "disease", "ownerName"]]
                fields.extend(str(r) for r in p.records)
                return any(kw in f.lower() for f in fields)
            results = [p for p in results if _match_keyword(p)]
        if filters.get("min_cost") is not None:
            results = [p for p in results if p.totalCost >= filters["min_cost"]]
        if filters.get("max_cost") is not None:
            results = [p for p in results if p.totalCost <= filters["max_cost"]]
        sort_by = filters.get("sort_by") or "id"
        order = filters.get("order", "asc")
        reverse = order == "desc"
        results.sort(key=lambda p: getattr(p, sort_by, p.id), reverse=reverse)
        return results

    def count(self, **filters) -> int:
        return len(self.list(**filters))
