"""
Seed script — fills the database with starting menu items and FAQs.

WHY this file exists:
A fresh database is empty. Instead of adding data by hand one-by-one,
this script adds a realistic starting menu + FAQ list in one go.
Run this ONCE after the database is created (or anytime you want to reset sample data).
"""

from app.database import SessionLocal, init_db, MenuItem, FAQ

def seed():
    init_db()  # WHY: make sure tables exist before inserting data
    db = SessionLocal()

    # --- Clear old sample data first (safe to re-run this script) ---
    db.query(MenuItem).delete()
    db.query(FAQ).delete()

    menu_items = [
        MenuItem(name="Chicken Biryani", category="Main Course", price=450, is_available=True, is_recommended=True),
        MenuItem(name="Beef Karahi", category="Main Course", price=650, is_available=True, is_recommended=True),
        MenuItem(name="Vegetable Pulao", category="Main Course", price=350, is_available=True, is_recommended=False),
        MenuItem(name="Seekh Kebab (6 pcs)", category="Starters", price=300, is_available=True, is_recommended=False),
        MenuItem(name="Chicken Tikka (4 pcs)", category="Starters", price=380, is_available=False, is_recommended=False),
        MenuItem(name="Soft Drink (500ml)", category="Drinks", price=100, is_available=True, is_recommended=False),
        MenuItem(name="Fresh Lime Soda", category="Drinks", price=150, is_available=True, is_recommended=True),
        MenuItem(name="Gulab Jamun (2 pcs)", category="Desserts", price=120, is_available=True, is_recommended=False),
    ]

    faqs = [
        FAQ(question="What are your opening hours?", answer="We are open every day from 12 PM to 11 PM."),
        FAQ(question="Do you deliver?", answer="Yes! We deliver within a 5 km radius of our restaurant."),
        FAQ(question="Do you have vegetarian options?", answer="Yes, we have several vegetarian dishes like Vegetable Pulao."),
        FAQ(question="How can I pay?", answer="We accept cash on delivery and card payments."),
        FAQ(question="How long does delivery take?", answer="Delivery usually takes 30-45 minutes depending on your location."),
    ]

    db.add_all(menu_items)
    db.add_all(faqs)
    db.commit()
    db.close()

    print(f"✅ Seeded {len(menu_items)} menu items and {len(faqs)} FAQs")


if __name__ == "__main__":
    seed()
