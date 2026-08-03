"""The credit book: what customers owe, and what they have paid.

Ghanaian wholesale runs on trade credit. A shopkeeper takes stock on Monday, pays
part of it on Wednesday and the rest a fortnight later, and the wholesaler tracks
that in a paper book. Until now the application recorded the sale and assumed it
was settled, so the question its users ask most often - who owes me money - was
the one it could not answer.

Bookkeeping only. No payment gateway is involved: a payment here is a record that
money arrived, entered by the person who received it. The MoMo reference field
exists because that is how this market reconciles - the customer sends a
transaction ID by SMS and the wholesaler writes it next to the amount.
"""
