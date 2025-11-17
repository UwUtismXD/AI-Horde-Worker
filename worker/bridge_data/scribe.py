"""The configuration of the bridge"""
import os

import requests
from loguru import logger

from worker.argparser.scribe import args
from worker.bridge_data.framework import BridgeDataTemplate


class KoboldAIBridgeData(BridgeDataTemplate):
    """Configuration object"""

    def __init__(self):
        super().__init__(args)
        self.kai_available = False
        self.model = None
        self.kai_url = "http://localhost:5000"
        self.max_length = int(os.environ.get("HORDE_MAX_LENGTH", "80"))
        self.max_context_length = int(os.environ.get("HORDE_MAX_CONTEXT_LENGTH", "1024"))
        self.branded_model = os.environ.get("HORDE_BRANDED_MODEL", "false") == "true"
        self.softprompts = {}
        self.current_softprompt = None
        self.openai_api = os.environ.get("HORDE_BACKEND_OPENAI_API", "false") == "true"

        self.nsfw = os.environ.get("HORDE_NSFW", "true") == "true"
        self.blacklist = list(filter(lambda a: a, os.environ.get("HORDE_BLACKLIST", "").split(",")))

    @logger.catch(reraise=True)
    def reload_data(self):
        """Reloads configuration data"""
        previous_url = self.horde_url
        super().reload_data()
        if hasattr(self, "scribe_name") and not self.args.worker_name:
            self.worker_name = self.scribe_name
        if args.kai_url:
            self.kai_url = args.kai_url
        if args.sfw:
            self.nsfw = False
        if args.blacklist:
            self.blacklist = args.blacklist
        if args.openai_api:
            self.openai_api = args.openai_api
        if args.custom_backend_name:
            self.custom_backend_name = args.custom_backend_name
        self.validate_kai()
        if self.kai_available and not self.initialized and previous_url != self.horde_url:
            logger.init(
                (
                    f"Username '{self.username}'. Server Name '{self.worker_name}'. "
                    f"Horde URL '{self.horde_url}'. KoboldAI Client URL '{self.kai_url}'"
                    "Worker Type: Scribe"
                ),
                status="Joining Horde",
            )

    @logger.catch(reraise=True)
    def validate_kai(self):
        logger.debug("Retrieving settings from KoboldAI Client...")
        try:
            version_req = requests.get(self.kai_url + "/version")
            if version_req.ok:
                self.backend_engine = f"aphrodite"
            else:
                logger.warning("Unable to determine OpenAI API compatible backend engine. Will report it as unknown to the Horde which will lead to less kudos rewards.")
                self.backend_engine = "unknown"
            if self.openai_api:
                req = requests.get(self.kai_url + "/v1/models")
                data = req.json()
                self.model = data["data"][0]['id'] if data.get("data") else None
                logger.debug(f"OpenAI API model: {self.model}")
                self.backend_engine += '~oai'
            else:
                req = requests.get(self.kai_url + "/api/latest/model")
                self.model = req.json()["result"]
                logger.debug(f"KoboldAI model: {self.model}")
                self.backend_engine += '~kai'
            # Normalize and customize model name if available
            if self.model and isinstance(self.model, str):
                logger.debug(f"Custom backend name: {getattr(self, 'custom_backend_name', 'Not set')}")
                # Apply custom backend name if set
                if hasattr(self, 'custom_backend_name') and self.custom_backend_name:
                    if "/" in self.model:
                        parts = self.model.split('/', 1)
                        self.model = f"{self.custom_backend_name}/{parts[1]}"
                    else:
                        self.model = f"{self.custom_backend_name}/{self.model}"
                # Normalize huggingface and local downloaded model names (only if no custom prefix added)
                elif "/" not in self.model:
                    self.model = self.model.replace("_", "/", 1)
            logger.debug(f"Model after processing: {self.model}")
            # Now using the settings from the bridge explicitly
            # req = requests.get(self.kai_url + "/api/latest/config/max_context_length")
            # self.max_context_length = req.json()["value"]
            # req = requests.get(self.kai_url + "/api/latest/config/max_length")
            # self.max_length = req.json()["value"]
            if not self.openai_api:
                if self.model not in self.softprompts:
                    req = requests.get(self.kai_url + "/api/latest/config/soft_prompts_list")
                    self.softprompts[self.model] = [sp["value"] for sp in req.json()["values"]]
                req = requests.get(self.kai_url + "/api/latest/config/soft_prompt")
                self.current_softprompt = req.json()["value"]
            # Fallback model if not provided by backend
            if not self.model and hasattr(self, 'fallback_model') and self.fallback_model:
                self.model = self.fallback_model
                logger.debug(f"Using fallback model: {self.model}")
        except requests.exceptions.JSONDecodeError:
            logger.error(f"Server {self.kai_url} is up but does not appear to be a KoboldAI server.")
            self.kai_available = False
            return
        except requests.exceptions.ConnectionError:
            logger.error(f"Server {self.kai_url} is not reachable. Are you sure it's running?")
            self.kai_available = False
            return
        self.kai_available = True
