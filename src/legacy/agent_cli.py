"""
Chạy agent bằng văn bản (text-first) — không cần micro.
"""

import os as _os, sys as _sys
# 'src' lên sys.path để chạy được `python legacy/agent_cli.py` (entry cũ, đã dời vào legacy/).
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from agent.actions_facade import AssistantActions
from agent.agent import Agent
from llm.client import build_default_llm_client
from features.contract import FeatureContext
from features.registry import build_registry
from services.scheduler import ReminderScheduler
from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)


def main():
    print("=== Trợ lý AI (agent, chế độ văn bản) ===")
    print("Gõ yêu cầu tiếng Việt. Gõ 'thoát' để kết thúc.\n")

    try:
        llm = build_default_llm_client()
    except RuntimeError as e:
        print(f"Không khởi tạo được LLM: {e}")
        return

    scheduler = ReminderScheduler(notify=lambda msg: print(f"\n🔔 Nhắc: {msg}"))
    scheduler.start()

    agent = Agent(llm=llm,
                  registry=build_registry(FeatureContext(actions=AssistantActions(), scheduler=scheduler))[0],
                  max_history_turns=config.MAX_HISTORY_TURNS,
                  memory_path=config.MEMORY_PATH or None)

    try:
        while True:
            try:
                user_text = input("Bạn: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nTạm biệt!")
                break
            if not user_text:
                continue
            if user_text.lower() in ("thoát", "exit", "quit"):
                print("Tạm biệt!")
                break

            try:
                response = agent.run(user_text).text
            except Exception as e:  # lỗi mạng/LLM không được làm sập CLI
                logger.error("Lỗi khi chạy agent: %s", e)
                response = "Xin lỗi, có lỗi khi xử lý yêu cầu."
            print(f"Trợ lý: {response}\n")
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
