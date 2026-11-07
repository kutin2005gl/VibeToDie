FROM golang:1.27-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/gateway ./cmd/server

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/gateway /gateway
COPY configs/routes.yaml /configs/routes.yaml
ENV ROUTES_FILE=/configs/routes.yaml
EXPOSE 8080
ENTRYPOINT ["/gateway"]
