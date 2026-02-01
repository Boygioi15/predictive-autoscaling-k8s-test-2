# ===== Build stage =====
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build
# output: dist/ (Vite) hoặc build/ (CRA)

# ===== Runtime stage =====
FROM nginx:alpine

# Xóa config mặc định
RUN rm /etc/nginx/conf.d/default.conf

# Copy build output
COPY --from=builder /app/dist /usr/share/nginx/html
# nếu CRA thì đổi dist -> build

# Nginx config đơn giản cho SPA
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
