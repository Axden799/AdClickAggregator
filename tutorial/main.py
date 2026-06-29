from fastapi import FastAPI
from enum import Enum
from pydantic import BaseModel

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}

# @app.get("/items/{item_id}")
# async def read_item(item_id: int):
#     return {"item_id": item_id}

# with the 2 functions below, fastAPI will execute me as its own route
# then all other routes go to the 2nd function. 
# ORDER MATTERS! If the me function came after, it would fall into the first matching function
# which will be function 2
# if 2 functions have the same header, the first one will always be executed and the other, never.

@app.get("/users/me")
async def read_user_me():
    return {"user_id": "the current user"}


@app.get("/users/{user_id}")
async def read_user(user_id: str):
    return {"user_id": user_id}


class ModelName(str, Enum):
    alexnet = "alexnet"
    resnet = "resnet"
    lenet = "lenet"

@app.get("/models/{model_name}")
async def get_model(model_name: ModelName):
    if model_name is ModelName.alexnet:
        return {"model_name": model_name, "message": "Deep Learning FTW!"}

    if model_name.value == "lenet":
        return {"model_name": model_name, "message": "LeCNN all the images"}

    return {"model_name": model_name, "message": "Have some residuals"}


# Starlette handles file paths using a path type. it matches any path, then validates
# its type with Pydantic like any other Python data type.
# note that the path must have a leading '/'. this means the path will have
# double slashes at the start of the path in the URL.

@app.get("/files/{file_path:path}")
async def read_file(file_path: str):
    return {"file_path": file_path}


# query parameters come after the '?' in the URL. 
# this defines how to filter or search for something.
# below, we query a list starting from index skip to index limit.

fake_items_db = [{"item_name": "Foo"}, {"item_name": "Bar"}, {"item_name": "Baz"}]


@app.get("/items/")
async def read_item(skip: int = 0, limit: int = 10):
    return fake_items_db[skip : skip + limit]

# query strings can be optionally None, to provide extra logic.

@app.get("/items/{item_id}")
async def read_item(item_id: str, q: str | None = None):
    if q:
        return {"item_id": item_id, "q": q}
    return {"item_id": item_id}

# support for booleans. if any value is passed to short

@app.get("/items/{item_id}")
async def read_item(item_id: str, q: str | None = None, short: bool = False):
    item = {"item_id": item_id}
    if q:
        item.update({"q": q})
    if not short:
        item.update(
            {"description": "This is an amazing item that has a long description"}
        )
    return item

# the JSON request body is used in almost every route. Either to get data or post it.
# below is an item class, extending from the BaseModel class from fastAPI.
# this class contains the relevant variables and data for the body.
# The /items/ route now posts this item.

class Item(BaseModel):
    name: str
    description: str | None = None
    price: float
    tax: float | None = None

# @app.post("/items/")
# async def create_item(item: Item):
#     return item

# below is an example on how to use the model.

@app.post("/items/")
async def create_item(item: Item):
    # convert to plain dict from Pydantic model
    item_dict = item.model_dump()
    if item.tax is not None:
        price_with_tax = item.price + item.tax
        item_dict.update({"price_with_tax": price_with_tax})
    return item_dict

