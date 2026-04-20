# Makefile for the Wumpus World DPLL client–server demo.

GO        ?= go
SERVER_DIR := .
CLIENT_DIR := client

BIN_DIR   := bin
SERVER_BIN := $(BIN_DIR)/wumpus-server
CLIENT_BIN := $(BIN_DIR)/wumpus-client
CURDIR := "C:\Users\emman\Downloads\P03_WumpusWorld"

.PHONY: all build server client run-server run-client clean fmt vet

all: build

build: server client

server:
	@mkdir -p $(BIN_DIR)
	cd $(SERVER_DIR) && $(GO) build -o $(CURDIR)/$(SERVER_BIN)

client:
	@mkdir -p $(BIN_DIR)
	cd $(CLIENT_DIR) && $(GO) build -o $(CURDIR)/$(CLIENT_BIN)

run-server: server
	$(SERVER_BIN)

run-client: client
	$(CLIENT_BIN) -games 1

# Play several games to get a stable average score.
bench: client
	$(CLIENT_BIN) -games 20

fmt:
	$(GO) fmt ./...
	cd $(CLIENT_DIR) && $(GO) fmt ./...

vet:
	$(GO) vet ./...
	cd $(CLIENT_DIR) && $(GO) vet ./...

clean:
	rm -rf $(BIN_DIR)
