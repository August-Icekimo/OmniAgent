FROM docker.io/library/golang:1.26-alpine AS builder

WORKDIR /app
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o skills-server .

FROM docker.io/library/alpine:latest
WORKDIR /root/
COPY --from=builder /app/skills-server .
EXPOSE 8001
CMD ["./skills-server"]
