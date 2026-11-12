/** "Chỉ kết quả của lần gọi mới nhất được áp dụng": đổi vai trò / đổi chuyến giữa chừng thì phản hồi chậm của lần gọi cũ
 *  (token hoặc id cũ) không được ghi đè dữ liệu mới, và các lần polling chồng nhau không làm dữ liệu nhảy ngược. */
export function latestGuard() {
  let n = 0
  return {
    /** Bắt đầu một lần gọi mới; trả mã của lần gọi đó. */
    next: () => ++n,
    /** Lần gọi `id` còn là lần mới nhất không? */
    current: (id: number) => id === n,
  }
}
