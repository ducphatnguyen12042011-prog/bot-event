import pymongo
import os

# Kết nối MongoDB từ Railway
MONGO_URL = os.getenv('MONGO_URL')
client = pymongo.MongoClient(MONGO_URL)
db = client['CentralCashSystem']
users_col = db['users']

class Economy:
    @staticmethod
    def get_user(user_id):
        user_id = str(user_id)
        user = users_col.find_one({"user_id": user_id})
        if not user:
            user = {"user_id": user_id, "coins": 10000, "win_amt": 0, "lose_amt": 0}
            users_col.insert_one(user)
        return user

    @staticmethod
    def update_balance(user_id, amount):
        user_id = str(user_id)
        # $inc là cộng dồn, số âm sẽ tự trừ
        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"coins": amount}},
            upsert=True
        )

    @staticmethod
    def update_payout(user_id, payout, win=0, lose=0):
        user_id = str(user_id)
        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"coins": payout, "win_amt": win, "lose_amt": lose}},
            upsert=True
        )
