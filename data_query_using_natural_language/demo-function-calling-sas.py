import os
import json
from typing import Any, Callable, Dict
from openai import AzureOpenAI
from dotenv import load_dotenv
from termcolor import colored
import saspy
import re

# Load environment variables
load_dotenv(".env")

# Azure OpenAI configuration
api_endpoint = os.getenv("OPENAI_URI")
api_key = os.getenv("OPENAI_KEY")
api_version = os.getenv("OPENAI_VERSION")
api_deployment_name = os.getenv("OPENAI_GPT_DEPLOYMENT")

# Create an AzureOpenAI client
client = AzureOpenAI(
    api_key=api_key,
    api_version=api_version,
    azure_endpoint=api_endpoint)

def sas_viya_url():
    # Ask the user for the new URL
    new_url = input("Enter your SAS Viya URL, for example: https://beret-p04222-rg.gelenable.sas.com: ")

    # Read the entire content of the file
    with open('sascfg_personal.py', 'r') as f:
        content = f.read()

    # Define a regex pattern to find the 'url' key inside 'httpsviya' dictionary
    pattern = r"(httpsviya\s*=\s*\{\s*(?:[^{}]*\n)*?\s*'url'\s*:\s*)'[^']*'"

    # Replacement string with the new URL
    replacement = r"\1'{}'".format(new_url)

    # Perform the substitution
    new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    # Write the updated content back to the file
    with open('sascfg_personal.py', 'w') as f:
        f.write(new_content)

    print("The 'url' value has been updated successfully in sascfg_personal.py.")

def log_message(message: str):
    """Logs error messages in red bold text."""
    print(colored(message, 'red', attrs=['bold']))

def print_in_color(key, value):
    """Prints key-value pairs in color for better readability."""
    if isinstance(value, str):
        formatted_value = value.replace("\\n", "\n").strip()
    else:
        formatted_value = str(value)  # Convert to string if not already
    print(colored(key, 'green', attrs=['bold']), colored(formatted_value, 'yellow', attrs=['bold']))


def execute_sas_code(sas, sas_code: str) -> str:
    """Executes the given SAS code using the provided SAS session."""
    sas_result = sas.submit(sas_code, results='TEXT')
    result_txt = sas_result['LST']
    return result_txt

def get_column_info(sas, library: str, table: str) -> str:
    """Retrieves column metadata from a SAS table."""
    sas_code = f"""
    proc contents data={library}.{table} out=column_metadata(keep=name type length format informat label) noprint;
    run;
    proc print data=column_metadata; run;
    """
    return execute_sas_code(sas, sas_code)

# SAS Tools
tools_list = [
    {
        "type": "function",
        "function": {
            "name": "execute_sas_code",
            "description": "This function is used to answer user questions about SAS Viya data by executing PROC SQL queries against the data source.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sas_code": {
                        "type": "string",
                        "description": f"""
                            The input should be a well-formed SAS code to extract information based on the user's question.
                            The code execution result will be returned as plain text, not in JSON format.
                        """,
                    }
                },
                "required": ["sas_code"],
                "additionalProperties": False,
            },
        },
    },
]

def call_functions(tool_calls, function_map) -> None:
    """
    Processes and executes function calls requested by the assistant.

    This function is responsible for calling the appropriate Python functions based on the
    function calls detected in the assistant's response. It extracts the function name and
    arguments from each function call, looks up the corresponding function in `function_map`,
    executes it with the provided arguments, and displays the result.

    Args:
        tool_calls (list): A list of function call objects extracted from the assistant's response.
                           Each function call contains the function name and its arguments.

    Raises:
        ValueError: If a function name from the tool call does not exist in `function_map`.

    """
    for tool_call in tool_calls:
        func_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        print_in_color("Executing function tool call", "")
        print_in_color("Function Name:", func_name)
        print_in_color("Arguments:", arguments)

        function = function_map.get(func_name)
        if not function:
            raise ValueError(f"Unknown function: {func_name}")

        result_df = function(arguments)
        print(result_df)


def process_message(sas, question: str, library: str, table: str, sas_table_info: str):
    """Processes the user's question and interacts with the OpenAI API.
    Calls functions as needed."""
    # Construct system message
    system_message = (
        "You are a data analysis assistant for data in SAS tables and libraries. "
        "Please be polite, professional, helpful, and friendly. "
        "Use the `execute_sas_code` function to execute SAS data queries, defaulting to aggregated data unless a detailed breakdown is requested. "
        "The function returns TXT-formatted results, nicely tabulated for use display. "
        f"Refer to the {library}.{table} metadata: {sas_table_info}. ",
        f"If a question is not related to {library}.{table} data or you cannot answer the question, "
        "then simply say, 'I can't answer that question. Please contact IT for more assistance.' "
        "If the user asks for help or says 'help', provide a list of sample questions that you can answer."
    )
    #print(system_message)

    messages = [{"role": "system", "content": str(system_message)},
                {"role": "user", "content": question}]

    # First API call: Ask the model to use the tool
    try:
        response = client.chat.completions.create(
            model=api_deployment_name,
            messages=messages,
            tools=tools_list,
            temperature=0.2,
            max_tokens=1512,
        )

        # Process the model's response
        response_message = response.choices[0].message
        tool_calls = getattr(response_message, "tool_calls", [])

        # addition
        messages.append(response_message)
        #print("Model's response: ", response_message)

        # Map the tool to the function defined above
        function_map: Dict[str, Callable[[Any], str]] = {
            "execute_sas_code": lambda args: execute_sas_code(sas, args["sas_code"]),
        }

        if tool_calls:
            call_functions(tool_calls, function_map)
            # new addition
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "execute_sas_code":
                    function_args = json.loads(tool_call.function.arguments)
                    #print(f"Function arguments: {function_args}")
                    sas_response = execute_sas_code(sas, sas_code=function_args.get("sas_code")
                    )
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": "get_current_time",
                        "content": sas_response,
                    })
        else:
            return response_message.content

        # Second API call: Get the final response from the model
        final_response = client.chat.completions.create(
        model=api_deployment_name,
        messages=messages,
        temperature=0.2,
        max_tokens=888
        )

        return final_response.choices[0].message.content

    except Exception as e:
        log_message(f"An error occurred: {e}")


# Main function
def main():
    """Main function to start the assistant."""
    # Choose the SAS Viya URL for SASPY config
    sas_viya_url()
    # Start SAS session
    print ('I am starting a SAS session. Thanks for your patience...')
    sas = saspy.SASsession(cfgfile='sascfg_personal.py', cfgname='httpsviya')
    library = 'sampsio'
    table = 'dmlcens'
    print(f"Library and table selected: {library} and {table}")
    # Fetch table metadata once at the beginning
    sas_table_info = get_column_info(sas, library=library, table=table)
    print('I am going to use this table metadata: ', sas_table_info)
    while True:
        print("SAS Viya and Azure OpenAI are listening. Write 'help' to get suggestions, 'change' to switch tables, 'stop' or press Ctrl-Z to end.")
        try:
            # Start session
            q = input("Enter your question: \n")
            if q.strip().lower() == "change":
                library = input("Enter the library name: ")
                table = input("Enter the table name: ")
                print(f"Library and table selected: {library} and {table}")
                # Fetch new table metadata after changing the library/table
                sas_table_info = get_column_info(sas, library=library, table=table)
                print('I am going to use this table metadata: ', sas_table_info)
            elif q.strip().lower() == "stop":
                print("Conversation ended.")
                sas.endsas()
                break
            else:
                assistant_result = process_message(sas, q, library, table, sas_table_info)
                print(assistant_result)
        except EOFError:
            break
        except Exception as e:
            # Handle exceptions
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()


"""
process_message("help")


process_message("Describe the data set.")

process_message("What is the proportion of people making a capital loss?")


process_message("What is the most frequent revenue (class) of people making a capital loss?")


process_message("What professions with a revenue (class) >50K are making a capital loss? Print the top three most frequent by occupation.")


process_message("What professions with a revenue (class) >50K are making a capital loss? Print the top three least frequent by occupation.")

process_message("What is the Meaning of Life?")


sas.endsas()
"""