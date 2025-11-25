import os
import json
import time
import requests
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
import google.generativeai as genai
from urllib.parse import quote

# Load environment variables from .env file
load_dotenv()

class OpenAIClientWithMemoryAndTools:
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMENI API key is required. Set GEMINI_API_KEY environment variable or pass api_key parameter.")
        
        self.model = model
        genai.configure(api_key=self.api_key)
        self.client = genai.GenerativeModel(self.model)
        # Initialize conversation history in memory
        self.conversation_history: List[Dict[str, str]] = []
    
    def get_weather(self, city: str) -> str:
        """
        Simple weather tool that fetches current weather for a city.
        Uses wttr.in (free, no API key required).
        """
        try:            
            city_enc = quote(city.strip())
            url = f"https://wttr.in/{city_enc}?format=j1&m&lang=en"
            
            response = requests.get(url, timeout=6)
            response.raise_for_status()
            data = response.json()
            
            cur = data["current_condition"][0]
            temp_c = cur.get("temp_C", "N/A")
            condition = cur["weatherDesc"][0]["value"]
            humidity = cur.get("humidity", "N/A")
            wind_kmph = cur.get("windspeedKmph", "N/A")
            feels_like_c = cur.get("FeelsLikeC", "N/A")
            
            return f"🌤️ Weather in {city}: {temp_c}°C, {condition}, Humidity: {humidity}%, Wind: {wind_kmph} km/h, Feels like: {feels_like_c}°C"
                
        except Exception as e:
            return f"Error fetching weather for {city}: {str(e)}"
    
    def chat_completion_with_tools(self, 
                                  user_message: str, 
                                  system_message: Optional[str] = None,
                                  max_tokens: int = 200,
                                  temperature: float = 0.7) -> str:
        """
        Make a chat completion request with tool calling capabilities.
        """
        # Build messages list with full conversation history
        messages = []
        
        # Add system message if provided
        if system_message:
            messages.append({"role": "system", "content": system_message})
        
        # Add all previous conversation messages
        messages.extend(self.conversation_history)
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        # Define available tools
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather information for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "The city name to get weather for"
                            }
                        },
                        "required": ["city"]
                    }
                }
            }
        ]
        
        try:
            # ✅ Convert stored conversation into Gemini's expected structure
            formatted_history = []
            for msg in self.conversation_history:
                if "content" in msg:
                    formatted_history.append({
                        "role": "user" if msg["role"] == "user" else "model",
                        "parts": [{"text": msg["content"]}]
                    })

            # ✅ Start a new chat session with properly formatted history
            chat = self.client.start_chat(history=formatted_history)

            # ✅ Send the user's new message
            response = chat.send_message(
                user_message,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    # tool_choice="AUTO"
                ),
                tools=tools,
                tool_config=genai.types.ToolConfig(mode="AUTO")

            )

            # ✅ Extract model response
            response_message = response.candidates[0].content
            print("=" * 100)
            print(response_message)
            print("=" * 100)

            # Gemini responses have .parts — get text + detect function calls
            response_text = ""
            tool_calls = []

            for part in getattr(response_message, "parts", []):
                if hasattr(part, "function_call") and part.function_call:
                    tool_calls.append({
                        "name": part.function_call.name,
                        "arguments": part.function_call.args
                    })
                elif hasattr(part, "text"):
                    response_text += part.text

            # ✅ Handle function calls if any
            if tool_calls:
                self.conversation_history.append({"role": "user", "content": user_message})
                tool_results = []

                for tc in tool_calls:
                    if tc["name"] == "get_weather":
                        args = tc["arguments"]
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {"city": args}
                        elif args is None:
                            args = {}
                        city = args.get("city", "Unknown")
                        tool_result = self.get_weather(city)
                        tool_results.append({
                            "tool_call_id": tc["name"],
                            "content": tool_result
                        })
                    else:
                        tool_results.append({
                            "tool_call_id": tc["name"],
                            "content": f"Tool '{tc['name']}' not implemented."
                        })

                # ✅ Add to conversation in Gemini format
                self.conversation_history.append({"role": "assistant", "content": response_text or ""})
                self.conversation_history.append({
                    "role": "tool",
                    "content": "\n".join([r["content"] for r in tool_results])
                })

                # ✅ Send follow-up message with tool results
                follow_up = "\n".join([r["content"] for r in tool_results])
                final_response = chat.send_message(
                    follow_up,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens
                    )
                    
    )

                ai_response = final_response.text.strip()
                self.conversation_history.append({"role": "assistant", "content": ai_response})
                return ai_response

            else:
                # ✅ Normal assistant response (no tools)
                ai_response = response_text.strip()
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": ai_response})
                return ai_response

        except Exception as e:
            return f"Error making Gemini API call: {str(e)}"

    
    def start_conversation(self):
        """
        Start a continuous conversation loop with memory and tool calling.
        """
        print("🤖 Chatbot with Memory and Tools is ready!")
        print("=" * 60)
        print("Available tools: get_weather (try asking about weather!)")
        print("Type 'quit' or 'exit' to end the conversation")
        print("Type 'history' to see conversation history")
        print("Type 'clear' to clear conversation history")
        print("=" * 60)
        
        system_message = """You are a helpful AI assistant with access to tools. 
        You can get weather information for cities using the get_weather tool.
        Keep responses concise and engaging. You can reference previous parts of our conversation.
        When asked about weather, use the get_weather tool to provide accurate information."""
        
        while True:
            try:
                # Get user input
                user_input = input("\n👤 You: ").strip()
                
                # Check for exit commands
                if user_input.lower() in ['quit', 'exit', 'bye']:
                    print("\n🤖 AI: Goodbye! Thanks for chatting!")
                    break
                
                # Check for special commands
                if user_input.lower() == 'history':
                    self.show_conversation_history()
                    continue
                
                if user_input.lower() == 'clear':
                    self.clear_conversation_history()
                    continue
                
                if not user_input:
                    print("Please enter a message.")
                    continue
                
                # Send to LLM with tool calling capabilities
                print("🔄 Processing", end="", flush=True)
                for _ in range(3):
                    time.sleep(1)
                    print(".", end="", flush=True)
                print()  # new line

                response = self.chat_completion_with_tools(
                    user_message=user_input,
                    system_message=system_message
                )
                print(f"🤖 AI: {response}")
                
            except KeyboardInterrupt:
                print("\n\n🤖 AI: Conversation interrupted. Goodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")
    
    def show_conversation_history(self):
        """Display the current conversation history."""
        if not self.conversation_history:
            print("📝 No conversation history yet.")
            return
        
        print("\n📝 Conversation History:")
        print("-" * 40)
        for i, message in enumerate(self.conversation_history, 1):
            role_emoji = "👤" if message["role"] == "user" else "🤖"
            content = message.get("content", "")
            
            if message["role"] == "tool":
                role_emoji = "🔧"
                # Check if this is a grouped tool result
                if "tool_results" in message and message["tool_results"]:
                    tool_results = message["tool_results"]
                    result_contents = []
                    for result in tool_results:
                        result_contents.append(f"[Tool Result: {result['content']}]")
                    content = " | ".join(result_contents)
                else:
                    content = f"[Tool Result: {content}]"
            elif message["role"] == "assistant":
                # Check if this is a tool call message
                if "tool_calls" in message and message["tool_calls"]:
                    tool_calls = message["tool_calls"]
                    tool_info = []
                    for tool_call in tool_calls:
                        tool_info.append(f"🔧 Called {tool_call.function.name} with args: {tool_call.function.arguments}")
                    
                    if content:
                        content = f"{content} {' '.join(tool_info)}"
                    else:
                        content = " ".join(tool_info)
            
            print(f"{i}. {role_emoji} {message['role'].title()}: {content}")
        print("-" * 40)
    
    def clear_conversation_history(self):
        """Clear the conversation history."""
        self.conversation_history.clear()
        print("🧹 Conversation history cleared!")


# Example usage and demo
if __name__ == "__main__":
    try:
        client = OpenAIClientWithMemoryAndTools()
        client.start_conversation()
    except ValueError as e:
        print(f"Setup error: {e}")
        print("Please set your OPENAI_API_KEY environment variable:")
        print("export OPENAI_API_KEY='your-api-key-here'")
        print("\nNote: Weather data is provided by wttr.in (free, no API key required)")
    except Exception as e:
        print(f"Unexpected error: {e}")