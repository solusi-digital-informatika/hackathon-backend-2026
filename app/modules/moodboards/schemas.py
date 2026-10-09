from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Role = Literal["overall", "color", "lighting", "composition", "character", "environment",
               "texture_material", "typography", "negative_reference"]
Basis = Literal["observasi", "interpretasi", "instruksi_pengguna"]
Confidence = Literal["tinggi", "sedang", "rendah"]


class Reference(StrictModel):
    id: str = Field(min_length=1)
    lokasi: str
    deskripsi_singkat: str


class Style(StrictModel):
    deskripsi: str
    ciri_utama: list[str]
    dasar: Basis
    referensi: list[str]
    keyakinan: Confidence


class Mood(StrictModel):
    nama: str
    penyebab_visual: str
    dasar: Basis
    referensi: list[str]
    keyakinan: Confidence


class Color(StrictModel):
    warna: str
    hex_perkiraan: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    peran_visual: str
    referensi: list[str]


class Elements(StrictModel):
    tekstur_dan_material: list[str]
    pencahayaan: list[str]
    bentuk_dan_garis: list[str]
    komposisi_dan_ruang: list[str]
    subjek_dan_latar: list[str]
    tipografi: list[str]


class Guidance(StrictModel):
    arahan: str
    alasan: str
    referensi: list[str]


class SharedGuidance(StrictModel):
    gunakan: list[Guidance]
    hindari: list[Guidance]


class VisualGroup(StrictModel):
    nama: str
    deskripsi: str
    referensi: list[str]


class Conflict(StrictModel):
    deskripsi: str
    referensi: list[str]


class HumanSummary(StrictModel):
    """Field names match MB-07; lifecycle/approval is stored separately."""
    status_analisis: Literal["cukup_jelas", "sebagian_jelas", "kurang_jelas"]
    status_panduan: Literal["usulan_perlu_konfirmasi", "dikonfirmasi_manusia"]
    ringkasan_visual: str
    referensi: list[Reference]
    gaya_utama: Style
    nuansa: list[Mood]
    palet_warna: list[Color]
    elemen_visual: Elements
    kelompok_visual: list[VisualGroup]
    panduan_bersama: SharedGuidance
    perbedaan_atau_konflik: list[Conflict]
    pertanyaan_klarifikasi: list[str]
    keterbatasan: list[str]

    @model_validator(mode="after")
    def valid_references(self):
        ids = [ref.id for ref in self.referensi]
        if len(ids) != len(set(ids)):
            raise ValueError("Reference IDs must be unique")
        known = set(ids)
        linked = [self.gaya_utama, *self.nuansa, *self.palet_warna, *self.kelompok_visual,
                  *self.panduan_bersama.gunakan, *self.panduan_bersama.hindari,
                  *self.perbedaan_atau_konflik]
        if any(set(item.referensi) - known for item in linked):
            raise ValueError("Unknown visual reference ID")
        return self


class MoodboardCreate(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    context: str = Field(default="", max_length=2000)
    intended_use: Literal["image", "video", "animation", "general"] = "general"


class MoodboardUpdate(StrictModel):
    revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    context: str | None = Field(default=None, max_length=2000)
    intended_use: Literal["image", "video", "animation", "general"] | None = None
    archived: bool | None = None


class SourceUpdate(StrictModel):
    revision: int = Field(ge=1)
    label: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    roles: list[Role] | None = Field(default=None, min_length=1)
    included: bool | None = None
    sequence_order: int | None = Field(default=None, ge=1)


class AnalysisRequest(StrictModel):
    revision: int = Field(ge=1)
    based_on_version_id: str | None = None


class ReviewDecision(StrictModel):
    finding_id: str
    decision: Literal["accepted", "edited", "rejected"]
    # An edited value has the same JSON shape as the original finding.
    value: str | dict | None = None
    strength: Literal["must", "prefer", "avoid", "reference_only"] = "reference_only"
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def require_edit(self):
        if self.decision == "edited" and self.value is None:
            raise ValueError("Edited findings require value")
        if self.decision != "edited" and self.value is not None:
            raise ValueError("value is only accepted for edited findings")
        if self.decision == "rejected" and self.strength != "reference_only":
            raise ValueError("Rejected findings cannot be constraints")
        return self


class AddedInstruction(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    strength: Literal["must", "prefer", "avoid", "reference_only"]


class ReviewRequest(StrictModel):
    revision: int = Field(ge=1)
    decisions: list[ReviewDecision] = Field(default_factory=list)
    # Conflict index -> explicit human resolution (unknown is allowed).
    conflict_resolutions: dict[str, str] = Field(default_factory=dict)
    instructions: list[AddedInstruction] | None = None


class ApprovalRequest(StrictModel):
    revision: int = Field(ge=1)


class ExportRequest(StrictModel):
    language: Literal["id", "en"] = "id"


class MoodboardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    title: str
    context: str
    intended_use: str
    revision: int
    archived: bool
    latest_approved_version_id: str | None
    created_at: datetime
    updated_at: datetime
