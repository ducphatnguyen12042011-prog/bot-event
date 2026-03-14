const express = require('express');
const axios = require('axios');
const app = express();
app.use(express.json());

// --- CẤU HÌNH ---
const DISCORD_WEBHOOK_URL = "DÁN_WEBHOOK_CỦA_BẠN_VÀO_ĐÂY";
const ADMIN_ID = "1482250836108115968";

// Danh sách trắng (Các ứng dụng không bị báo cáo là "lạ")
const WHITE_LIST = ['discord', 'valorant', 'cs2', 'csgo', 'steam', 'chrome', 'explorer', 'taskmgr', 'nvcontainer', 'nvidia', 'svchost', 'systemsettings'];

app.post('/report', async (req, res) => {
    const { pc_name, user, processes } = req.body;
    let blackListFound = [];
    let strangeApps = [];

    processes.forEach(p => {
        const name = p.Name.toLowerCase();
        // 1. Check từ khóa Hack/Cheat
        if (['cheat', 'hack', 'injector', 'vape', 'aimbot', 'engine'].some(kw => name.includes(kw))) {
            blackListFound.push(p.Name);
        }
        // 2. Check ứng dụng lạ (ngoài whitelist)
        if (!WHITE_LIST.some(w => name.includes(w))) {
            strangeApps.push(p.Name);
        }
    });

    if (blackListFound.length > 0 || strangeApps.length > 0) {
        const payload = {
            content: `<@${ADMIN_ID}> 🚨 **CẢNH BÁO TỪ MÁY: ${pc_name}**`,
            embeds: [{
                title: `Vận động viên: ${user}`,
                color: blackListFound.length > 0 ? 15158332 : 16776960,
                fields: [
                    { name: "❌ PHẦN MỀM CẤM", value: blackListFound.length > 0 ? blackListFound.join(", ") : "Sạch", inline: false },
                    { name: "❓ ỨNG DỤNG LẠ", value: strangeApps.length > 0 ? strangeApps.slice(0, 15).join(", ") : "Không có", inline: false }
                ],
                timestamp: new Date()
            }]
        };
        await axios.post(DISCORD_WEBHOOK_URL, payload);
    }
    res.status(200).send("OK");
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Backend running on port ${PORT}`));
