class Incident:
    def __init__(self, incident_id, description):
        self.incident_id = incident_id
        self.description = description
        self.status = "NEW"

    def assign(self):
        if self.status != "NEW":
            raise Exception("Can only assign a NEW incident")
        self.status = "ASSIGNED"