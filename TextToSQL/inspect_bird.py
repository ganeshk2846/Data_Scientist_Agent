from datasets import load_dataset

ds = load_dataset("birdsql/bird_mini_dev")
bird = ds["mini_dev_sqlite"]

print("Total questions:", len(bird))
print("\nFirst question:")
print("Database:", bird[0]["db_id"])
print("Question:", bird[0]["question"])
print("Evidence:", bird[0]["evidence"])
print("Reference SQL:", bird[0]["SQL"])
print("Difficulty:", bird[0]["difficulty"])
