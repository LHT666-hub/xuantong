from pydantic import BaseModel, Field


class NutritionCandidateRecipe(BaseModel):
    id: str
    title: str
    minutes: int = Field(ge=1, le=240)
    ingredient_ids: list[str] = []
    tags: list[str] = []


class NutritionRecommendationRequest(BaseModel):
    pantry_ids: list[str] = []
    excluded_ids: list[str] = []
    city: str = ""
    max_minutes: int = Field(default=30, ge=5, le=240)
    low_salt: bool = False
    likes_spicy: bool = False
    staple_preference: str = ""
    meal_context: str = ""
    goal: str = ""
    health_note: str = ""
    medication_note: str = ""
    candidate_recipes: list[NutritionCandidateRecipe]


class NutritionRecommendationResponse(BaseModel):
    model: str
    recipe_ids: list[str]
    summary: str
    notices: list[str] = []
    degraded: bool = False
