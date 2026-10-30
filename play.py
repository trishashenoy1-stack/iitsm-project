from domain.incident import Incident
from domain.enums import Status

ticket = Incident("INC1", "Payment app down")
print(ticket.status)           # shows Status.NEW
print(ticket.status.value)     # shows NEW
print(ticket.status == Status.NEW)

print(Status("NEW"))           # works
print(Status("NEWW"))          # error: not on the menu