import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB_NAME")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

users_collection = db["users"]
session_collection = db["session"]
interaction_collection = db["interaction"]
teacher_collection = db["teacher"]
student_collection = db["student"]
evaluator_collection = db["evaluator"]
scorer_collection = db["scorer"]
