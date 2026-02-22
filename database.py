import pymongo
import os

# Kết nối tới MongoDB (Lấy link từ biến môi trường Railway)
MONGO_URL = os.getenv('MONGO_URL')
client = pymongo.MongoClient(MONGO_URL)
db = client['GameDatabase']
users_col = db['users']

class Economy:
    @staticmethod
    def get_balance(user_id):
        user_id = str(user_id) # Luôn lưu ID dưới dạng chuỗi
        user = users_col.find_one({"user_id": user_id})
        if not user:
            # Tạo mới nếu chưa có (Tặng 10,000 làm vốn)
            user = {"user_id": user_id, "coins": 10000, "win_amt": 0, "lose_amt": 0}
            users_col.insert_one(user)
        return user['coins']

    @staticmethod
    def update_balance(user_id, amount):
        user_id = str(user_id)
        # $inc là lệnh cộng dồn (số âm sẽ là trừ)
        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"coins": amount}},
            upsert=True
        )

    @staticmethod
    def update_stats(user_id, coins=0, win=0, lose=0):
        user_id = str(user_id)
        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"coins": coins, "win_amt": win, "lose_amt": lose}},
            upsert=True
        )
