"""IoT is one feature: inventory, environment, alerts and climate control."""

from features.contract import Feature
from features.iot import tools
from features.iot.fast import FAST_PATHS


FEATURE = Feature(
    name="iot",
    register=tools.register,
    fast_paths=FAST_PATHS,
    requires=("iot",),
    prompt=(
        "Khi người dùng hỏi môi trường hoặc thiết bị trong phòng, gọi get_room_environment. "
        "Nhiệt độ hiện tại: metric=temperature_c, không hours. stale: đọc giá trị gần nhất và nói đã cũ. "
        "Khi người dùng yêu cầu bật/tắt máy lạnh hoặc hẹn giờ tắt, gọi control_room_ac. "
        "Yêu cầu tự bật theo ngưỡng: gọi configure_climate_automation; chỉ xác nhận khi status=saved. "
        "Phải nóng trên ngưỡng trong 20 phút và có người; vẫn áp dụng thời gian chờ. "
        "Bật trong một tiếng nghĩa là action=on và timer_minutes=60; bật ngay và tự tắt sau đó. "
        "Khi hỏi còn lịch tắt máy lạnh hay tắt lúc mấy giờ, gọi get_room_environment "
        "không có metric, đọc room.automation.off_timer_status và run_until_local; "
        "không dùng list_reminders. Nếu off_timer_status là none, nói không còn lịch tắt "
        "đang chờ; nếu overdue_retrying, nói đã quá giờ nhưng lệnh chưa gửi được. "
        "Nếu nhiều phòng mà câu nói không chỉ rõ phòng, hỏi lại. Phân biệt queued_for_mqtt "
        "với node_result_ok_uncorrelated: kết quả legacy không có request_id, nên chỉ "
        "là phản hồi của node trong cửa sổ một lệnh, chưa xác nhận máy lạnh vật lý. "
        "Nếu quality là stale, không mô tả số đo là hiện tại."
    ),
    router_hint="- iot: thiết bị thông minh, nhiệt độ/độ ẩm phòng, máy lạnh, hẹn tắt, MQTT",
    max_spec_chars=1800,
)
