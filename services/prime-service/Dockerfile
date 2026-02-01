FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install --only=production

COPY dist ./dist
# nếu chưa build sẵn thì:
# COPY . .
# RUN npm run build

ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000
CMD ["node", "dist/main.js"]
