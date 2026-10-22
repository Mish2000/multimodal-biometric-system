// The Hebrew text of the server's error codes (H23: the API answers with codes, the client words them).
import type { ApiResult } from '../../shared/bridge'

const ERRORS: Record<string, string> = {
  server_unreachable: 'השרת לא זמין. צריך להפעיל אותו ולנסות שוב.',
  wrong_credentials: 'שם המשתמש או הסיסמה שגויים.',
  account_disabled: 'החשבון הזה מושבת. אפשר לפנות למנהל המערכת.',
  invalid_username: 'שם משתמש: 3 עד 32 אותיות או ספרות, בכל שפה; מותר . _ - באמצע.',
  invalid_email: 'כתובת האימייל לא תקינה.',
  weak_password: 'הסיסמה צריכה להכיל 12 עד 256 תווים.',
  username_taken: 'שם המשתמש הזה תפוס.',
  email_taken: 'האימייל הזה כבר רשום.',
  invalid_national_id: 'מספר הזהות לא תקין: ספרת הביקורת לא מתאימה.',
  national_id_registered: 'מספר הזהות הזה כבר רשום במערכת.',
  already_registered: 'החשבון נרשם בינתיים. אפשר לנסות להיכנס.',
  not_signed_in: 'הכניסה הסתיימה. צריך להיכנס שוב.',
  password_change_required: 'צריך קודם להחליף את הסיסמה החד-פעמית.',
  wrong_password: 'הסיסמה שגויה.',
  same_password: 'הסיסמה החדשה חייבת להיות שונה מהנוכחית.',
  last_administrator: 'אי אפשר להשבית את המנהל הפעיל האחרון.',
  no_such_account: 'החשבון לא נמצא.',
  forbidden: 'אין לחשבון הזה הרשאה לפעולה.',
  invalid_request: 'חלק מהשדות חסרים או ארוכים מדי.',
}

export function errorText(result: ApiResult): string {
  if (result.ok) return ''
  if (result.error === 'too_many_attempts') {
    return `יותר מדי ניסיונות שגויים. אפשר לנסות שוב בעוד ${result.retryAfter ?? 'כמה'} שניות.`
  }
  return ERRORS[result.error] ?? 'אירעה שגיאה לא צפויה.'
}

export const MODALITY_NAMES: Record<string, string> = { fingerprint: 'טביעת אצבע', face: 'פנים', voice: 'קול' }

export const AUDIT_ACTIONS: Record<string, string> = {
  first_administrator: 'נוצר המנהל הראשון',
  create_administrator: 'נוצר מנהל',
  disable_account: 'חשבון הושבת',
  enable_account: 'חשבון הופעל',
  change_threshold: 'סף שונה',
}
