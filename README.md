# LeanQuantHub

LeanQuantHub 是基于 Lean 引擎的本地化量化研究与回测平台，提供项目管理、算法版本、数据管线、回测与报告的一体化协作体验。前端参考 QuantConnect 交互风格，后端基于 FastAPI + MySQL，核心回测由 Lean Runner 触发。

## 核心能力
- 项目/算法/回测/报告的完整链路管理
- 主题化投资组合配置（可编辑主题、权重、关键词与手动股票）
- 数据管线：成分构建、指标抓取、价格下载与质量查看
- Lean 回测集成与报告归档

## 目录结构
- ackend/：FastAPI API + MySQL 元数据
- rontend/：React + Vite 前端
- scripts/：数据管线与工具脚本
- configs/：默认主题与权重模板
- lgorithms/：Lean 策略脚本
- deploy/：部署与数据库脚本

## 快速开始（服务器）
1. 初始化数据库
`ash
mysql -u <user> -p < /app/stocklean/deploy/mysql/schema.sql
`
2. 配置环境变量
`ash
cp /app/stocklean/backend/.env.example /app/stocklean/backend/.env
# 填写 DB_* 与 Lean 路径
`
3. 启动服务（systemd 用户服务）
`ash
systemctl --user restart stocklean-backend stocklean-frontend
`
4. 访问
- 前端：http://<server>:8081
- 后端：http://<server>:8021

## 本地开发
后端：
`ash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8021
`
前端：
`ash
cd frontend
npm install
npm run dev
`

## 配置与安全
- 所有敏感配置使用 .env，请勿提交到仓库。
- .env.example 提供模板，默认已去敏。

## 项目地址
- GitHub：https://github.com/hellcatjack/LeanQuantHub
