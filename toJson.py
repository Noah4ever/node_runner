# Open the input file and read its content
with open("toJsonFile.txt", "r") as input_file:
    content = input_file.read()

# Perform the replacements
content = content.replace("'", '"')  # Replace single quotes with double quotes
content = content.replace(" False", " false").replace(
    " True", " true"
)  # Replace False/True with lowercase equivalents
content = content.replace(" None", '"None"')  # Replace None with "None"

# Write the modified content to the output file
with open("toJsonFile.json", "w") as output_file:
    output_file.write(content)

print("File converted and saved as 'toJsonFile.json'.")
