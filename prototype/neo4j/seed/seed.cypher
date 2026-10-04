MATCH (p:Person {customer_id: 'C1024'})
OPTIONAL MATCH (w:WithdrawalEvent {purpose: 'MARKETING'})
RETURN p, w;
