.PHONY: install auth push pull test dry-run list clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install ElevenLabs CLI
	npm install -g @elevenlabs/cli

auth: ## Login to ElevenLabs
	elevenlabs auth login

push: ## Push all agents to ElevenLabs
	elevenlabs agents push

pull: ## Pull agents from ElevenLabs to local
	elevenlabs agents pull

dry-run: ## Preview what would change on push
	elevenlabs agents push --dry-run

test: ## Run all agent tests
	bash scripts/run-tests.sh

list: ## List agents and status
	elevenlabs agents list

clean: ## Remove generated files
	rm -rf .agents/
