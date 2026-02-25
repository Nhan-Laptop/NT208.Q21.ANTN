# AIRA Frontend MVP

Next.js frontend cho AIRA backend (FastAPI), tập trung vào flow MVP:

- Login bằng Bearer token in-memory
- Chat sessions + messages
- Scientific tools UI
- Upload/download file
- Admin dashboard (overview/users/files/storage)

## Setup

1. Copy env:

```bash
cp .env.example .env.local
```

2. Cấu hình API URL trong `.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

3. Cài dependency và chạy:

```bash
npm install
npm run dev
```

## Notes

- Token chỉ lưu trong memory; reload trang sẽ cần login lại.
- Frontend không hardcode backend URL, mọi API call dùng `NEXT_PUBLIC_API_BASE_URL`.
- Các lỗi phổ biến được hiển thị rõ theo mã: `401`, `403`, `413`, `415`, `429`.
