using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace ScannerCapture
{
    /// <summary>A JSON object that keeps its keys in insertion order, so generated files are stable.</summary>
    sealed class JsonObject : IEnumerable<KeyValuePair<string, object>>
    {
        readonly List<KeyValuePair<string, object>> _items = new List<KeyValuePair<string, object>>();

        public void Add(string key, object value) => _items.Add(new KeyValuePair<string, object>(key, value));

        public IEnumerator<KeyValuePair<string, object>> GetEnumerator() => _items.GetEnumerator();

        IEnumerator IEnumerable.GetEnumerator() => _items.GetEnumerator();

        /// <summary>Indented JSON with LF line endings and a final newline.</summary>
        public string ToJson()
        {
            var sb = new StringBuilder();
            Write(sb, this, 0);
            sb.Append('\n');
            return sb.ToString();
        }

        static void Write(StringBuilder sb, object value, int depth)
        {
            switch (value)
            {
                case null:
                    sb.Append("null");
                    break;
                case string s:
                    WriteString(sb, s);
                    break;
                case bool b:
                    sb.Append(b ? "true" : "false");
                    break;
                case double d:
                    sb.Append(double.IsNaN(d) || double.IsInfinity(d) ? "null" : d.ToString("R", CultureInfo.InvariantCulture));
                    break;
                case float f:
                    sb.Append(float.IsNaN(f) || float.IsInfinity(f) ? "null" : f.ToString("R", CultureInfo.InvariantCulture));
                    break;
                case int _:
                case long _:
                case short _:
                case uint _:
                    sb.Append(Convert.ToString(value, CultureInfo.InvariantCulture));
                    break;
                case JsonObject obj:
                    if (obj._items.Count == 0) { sb.Append("{}"); break; }
                    sb.Append("{\n");
                    for (int i = 0; i < obj._items.Count; i++)
                    {
                        Indent(sb, depth + 1);
                        WriteString(sb, obj._items[i].Key);
                        sb.Append(": ");
                        Write(sb, obj._items[i].Value, depth + 1);
                        sb.Append(i + 1 < obj._items.Count ? ",\n" : "\n");
                    }
                    Indent(sb, depth);
                    sb.Append('}');
                    break;
                case IEnumerable list:
                    var items = new List<object>();
                    foreach (var item in list) items.Add(item);
                    if (items.Count == 0) { sb.Append("[]"); break; }
                    sb.Append("[\n");
                    for (int i = 0; i < items.Count; i++)
                    {
                        Indent(sb, depth + 1);
                        Write(sb, items[i], depth + 1);
                        sb.Append(i + 1 < items.Count ? ",\n" : "\n");
                    }
                    Indent(sb, depth);
                    sb.Append(']');
                    break;
                default:
                    WriteString(sb, Convert.ToString(value, CultureInfo.InvariantCulture));
                    break;
            }
        }

        static void Indent(StringBuilder sb, int depth) => sb.Append(' ', 2 * depth);

        static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }
}
