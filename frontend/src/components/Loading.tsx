export function Loading({ label = '불러오는 중…' }: { label?: string }) {
  return <p className="loading" role="status">{label}</p>
}

export function ErrorBox({ message }: { message: string }) {
  return <p className="error" role="alert">오류: {message}</p>
}
