from typing import Literal

from pydantic import BaseModel,EmailStr,Field


class UserCreate(BaseModel):
    email:EmailStr
    password:str = Field(max_length=72,min_length=8)


class UserOut(BaseModel):
    user_id : int 
    email:EmailStr

class Token(BaseModel):
    access_token:str
    token_type:Literal["bearer"] = "bearer"


