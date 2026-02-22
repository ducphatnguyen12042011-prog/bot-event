const mongoose = require('mongoose');

// Kết nối tới MongoDB bằng biến môi trường trên Railway
const connectDB = async (url) => {
    try {
        await mongoose.connect(url);
        console.log("✅ Đã kết nối hệ thống ví tập trung!");
    } catch (err) {
        console.error("❌ Lỗi kết nối:", err);
    }
};

// Định nghĩa khung dữ liệu người dùng
const userSchema = new mongoose.Schema({
    userId: { type: String, required: true, unique: true },
    cash: { type: Number, default: 0 }
});

const User = mongoose.model('User', userSchema);

// Các hàm bổ trợ để gọi cho nhanh
const Economy = {
    // Lấy số dư
    getBalance: async (userId) => {
        let user = await User.findOne({ userId });
        if (!user) {
            user = await User.create({ userId, cash: 1000 }); // Tặng 1000 cho người mới
        }
        return user.cash;
    },

    // Cộng hoặc trừ tiền (Dùng số âm để trừ)
    updateCash: async (userId, amount) => {
        return await User.findOneAndUpdate(
            { userId },
            { $inc: { cash: amount } },
            { new: true, upsert: true }
        );
    }
};

module.exports = { connectDB, Economy };
