from nornir import InitNornir
from nornir_netmiko.tasks import netmiko_send_command
from nornir_utils.plugins.functions import print_result

# Khởi tạo Nornir, nó sẽ tự động đọc file config.yaml
nr = InitNornir(config_file="config.yaml")

print("--- Bắt đầu kiểm tra kết nối tới thiết bị mạng ---")

# Chạy tác vụ: gửi lệnh 'show ip interface brief' tới tất cả thiết bị
# Lệnh này nhanh và lý tưởng để kiểm tra kết nối
result = nr.run(task=netmiko_send_command, command_string="show ip interface brief")

print("--- Kết quả trả về ---")
# In kết quả ra màn hình một cách đẹp đẽ
print_result(result)