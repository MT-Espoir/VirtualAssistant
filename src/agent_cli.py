"""
Chạy agent bằng văn bản (text-first) — không cần micro.

Dùng để phát triển & demo vòng lặp tool-calling: gõ câu lệnh tiếng Việt, agent
gọi tool điều khiển máy tính rồi trả lời. Cần cài 'anthropic' và có ANTHROPIC_API_KEY.

    cd src && python agent_cli.py
"""

from core.actions_facade import AssistantActions
from core.agent import Agent
from core.llm_client import build_default_llm_client
from core.tools import build_default_registry
from services.scheduler import ReminderScheduler
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
                  registry=build_default_registry(AssistantActions(), scheduler=scheduler))

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
                response = agent.run(user_text)
            except Exception as e:  # lỗi mạng/LLM không được làm sập CLI
                logger.error("Lỗi khi chạy agent: %s", e)
                response = "Xin lỗi, có lỗi khi xử lý yêu cầu."
            print(f"Trợ lý: {response}\n")
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
